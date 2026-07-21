from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import json
import os
import re
import threading
import time
from typing import Any, Callable, Final, Optional

# NOTE: engine.dispatcher is imported LAZILY inside ExecutionLoop.__init__ (see
# _build_dispatcher) rather than at module load. Importing it here would create
# a load-order cycle:
#   engine.loop -> engine.dispatcher -> engine.tool_registry -> tools.base
# and, more importantly, engine.loop was historically the linchpin that forced
# engine/__init__ -> engine.loop -> llm_router -> core -> core.kernel.events to
# re-enter mid-import. Injecting the dispatcher via DI + a Protocol keeps the
# module-level import graph acyclic.
from engine.consent import ConsentManager
from core.kernel.events import bus
from engine.interfaces import DispatcherProtocol
from engine.state import RuntimeState, GoalSpec, parse_goal_command, build_goal_block
from engine.goal_verifier import evaluate_goal_exit, MAX_GOAL_RETRIES
from engine._loop_types import _LoopSignal, _ToolInteraction, _LoopCtx
from engine._loop_types import TOOL_FEWSHOT_FALLBACK
from engine._context import _ContextMixin
from engine._budget import _BudgetMixin
from engine._convergence import _ConvergenceMixin
from engine._tool_runner import _ToolRunnerMixin
from core.permissions import PermissionEngine, PermissionDecision

from core.parser import extract_command, extract_json_from_response, validate_tool_call, ToolCall
from tools.models import ToolResult
from core.security import is_safe_command
from core.utils import truncate, safe_strip
from pathlib import Path
from core.evidence import EvidenceLog, VerifierError
from core.constants import is_chitchat
from core.storage import load_memory, write_lesson
from core.workspace import load_workspace_context
from core.sanitize import sanitize
from core.ui_bridge import get_bridge, _TIMEOUT_REPLY
from core.prompts import BROWSER_FEWSHOT_EXAMPLES, FALLBACK_RESTRICTED_PROMPT, CRITICAL_RULES_FOR_TOOL_CALLING
from core.context_compactor import ContextCompactor, CompactionConfig

import logging

# Single file handle for parser-debug tracing, opened once at module load
# (not per LLM step) to avoid repeated open()/close() in the hot path.
_parser_debug_logger = logging.getLogger("nabd.parser_debug")
if not _parser_debug_logger.handlers:
    try:
        from pathlib import Path as _PD
        _PD("logs").mkdir(exist_ok=True)
        _pd_handler = logging.FileHandler("logs/parser_debug.log", encoding="utf-8")
        _pd_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        _parser_debug_logger.addHandler(_pd_handler)
        _parser_debug_logger.setLevel(logging.DEBUG)
        _parser_debug_logger.propagate = False
    except Exception:
        pass


# ---------------------------------------------------------------------
# Phase 2: Dynamic Few-Shot for small / fallback models
# ---------------------------------------------------------------------
#
# Small or local fallback models (e.g. "gemma-2-9b-it", "mini", "local") tend to
# wrap tool calls in prose or markdown fences. A tight few-shot anchor showing
# the exact one-line JSON shape measurably reduces those hallucinations. It is
# only injected when the active model is detected as a small/fallback tier so we
# never bloat the context for capable models.

_SMALL_FALLBACK_MODEL_KEYWORDS: Final[tuple[str, ...]] = (
    "9b", "8b", "mini", "fallback", "local",
)

# P0.2 (step6): pure helpers + constants extracted to engine/_loop_helpers.py
# to shrink this god-module. Re-exported here so existing ``from engine.loop
# import _prompt_requires_investigation`` call sites and tests keep working.
from engine._loop_helpers import (  # noqa: F401
    _prompt_requires_investigation,
    _normalize_response,
    _extract_cmd_or_path,
    _extract_final_answer,
    _looks_like_tool_call,
    _is_thought_only,
    MAX_SELF_CORRECT,
    MAX_PROVIDER_FAIL_STREAK,
    FALLBACK_ALLOWED_TOOLS,
    CHAT_WINDOW,
    _has_active_goal,
    TOOL_WINDOW,
    MAX_CRITICAL_FULL,
    FORBIDDEN_THOUGHT_PATTERNS,
    _resolve_default_provider,
    _resolve_default_verifier,
    _build_dispatcher,
    _derive_read_hint,
    _type_name,
)


class ToolRequiredError(RuntimeError):
    """Raised when the agent answered without using required tools."""
    pass



def _type_name(t: Any) -> str:
    """Map a Python type annotation to a short human-readable name."""
    if t is str:
        return "str"
    if t is int:
        return "int"
    if t is float:
        return "float"
    if t is bool:
        return "bool"
    if t is list:
        return "list"
    if t is dict:
        return "dict"
    return str(t).split("'")[1] if "'" in str(t) else str(t)



class ExecutionLoop(_ContextMixin, _BudgetMixin, _ConvergenceMixin, _ToolRunnerMixin):
    """
    Autonomous execution engine with Self-Correction Loop.
    """

    POLL_DELAY: Final[float] = 0.5

    def __init__(
        self,
        state: RuntimeState,
        *,
        max_output_len: int = 2000,
        llm_provider: Callable[[list[dict[str, Any]]], str] | None = None,
        verifier_provider: Callable[[str, str, str, Any], str] | None = None,
        dispatcher: DispatcherProtocol | None = None,
        evidence_log: EvidenceLog | None = None,
        logger: Any = None,
        model_identifier: str | None = None,
        no_stream: bool = False,
    ) -> None:

        self.state = state
        # Dependency Injection: the dispatcher is injected (or built lazily) so
        # engine.loop never needs a module-level import of engine.dispatcher.
        self.dispatcher = dispatcher or _build_dispatcher(state)
        self.llm_provider = llm_provider or _resolve_default_provider()
        self._verifier_provider = verifier_provider or _resolve_default_verifier()
        self._verifier_calls = 0  # step6: per-run budget for independent checker
        self.max_output_len = max_output_len
        self._recent_calls: deque[ToolCall] = deque(maxlen=16)
        self.evidence_log = evidence_log or EvidenceLog()
        # Optional logger for routing provider fallback messages into the
        # session log file instead of stdout (keeps the REPL clean).
        self._logger = logger
        self._self_correct_count = 0
        self._provider_fail_streak = 0
        self._last_tool_signature: str | None = None
        self._fixation_count: int = 0
        self._force_final: bool = False  # set by Fixation Breaker to hard-stop looping
        self._force_tool: bool = False  # Phase C: force tool call on next LLM iteration when reads < 3
        self._executed_sigs: set[str] = set()  # all tool-call signatures executed this run
        self._redundant_count: int = 0  # count of already-seen (cycled) calls
        self._evidence_rejection_count: int = 0
        self.MAX_EVIDENCE_RETRIES: int = 3  # السماح بـ 3 محاولات لتصحيح الإجابة
        # Phase F: one-time synthesis directive flag.
        self._synthesis_directive_injected: bool = False
        # Phase D: unified read counter tracking across iterations.
        self._last_read_count: int = 0  # previous iteration's read count (for progress detection)
        # Phase2: the active model identifier. Injected by callers that know the
        # resolved model (e.g. the router); defaults to the env-configured model
        # so existing callers that omit it still get a meaningful identifier.
        self.model_identifier = model_identifier or os.getenv(
            "OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-free"
        )
        # Phase P4: opt out of live token streaming. When True, _invoke_llm_and_normalize
        # skips the SSE path and always uses the full-response (non-streaming) call.
        # Sources (in precedence order): explicit arg > NABD_NO_STREAM env > stream on.
        self._no_stream = no_stream or (
            os.getenv("NABD_NO_STREAM", "").lower() in ("1", "true", "yes")
        )
        # Phase5 (GoalSpec): an explicit, verifiable session objective. It may
        # be injected here, or set earlier on state.active_goal via ``/goal``.
        # The verifier enforces it before any "Success" termination.
        self._goal = state.active_goal if isinstance(state.active_goal, GoalSpec) else None
        # Phase5 (Workspace Context): project-specific instructions (AGENTS.md /
        # .agents/config.md), loaded per run and injected into the system anchor.
        # Defaults to ""; set in run() before the loop starts. Fail-safe empty.
        self._workspace_context: str = ""
        # Per-run context; allocated in run() before the loop begins.
        self._ctx: Optional[_LoopCtx] = None
        # ToolRegistry (populated by AppContext.build() before any ExecutionLoop
        # is constructed) is the single source of truth for tool schemas.
        self.all_tools = self._get_registry_schemas()
        self._compactor = ContextCompactor()
        # Phase 3 (tech-debt fix): static runtime-context (AGENT.md rules +
        # discovered skills + taste summary) is invariant for the whole run,
        # so it is built ONCE in run() and cached here instead of re-read from
        # disk on every LLM call. Consumed by _inject_runtime_context().
        self._static_context_cache: Optional[str] = None


    @staticmethod
    def _get_registry_schemas() -> dict:
        """Return all tool schemas directly from the live ``ToolRegistry``.

        The registry is the authoritative source of truth; no legacy fallback
        dict is merged. Every registered tool is visible to the model.
        """
        try:
            from engine.tool_registry import registry

            schemas: dict[str, dict[str, Any]] = {}
            for schema in registry.get_all_schemas():
                name = schema.get("name")
                if name:
                    schemas[name] = {
                        "required": schema.get("required", {}),
                        "optional": schema.get("optional", {}),
                        "description": schema.get("description", ""),
                    }
            return schemas
        except Exception:
            return {}

    def _is_small_or_fallback_model(self) -> bool:
        """Return True when the active model is a small/local/fallback tier.

        Detection is keyword-based on the model identifier: suffixes like "9b",
        "8b", "mini", and the literals "fallback"/"local" mark the weaker tiers
        that benefit from the Phase 2 few-shot anchor and terse corrections.
        """
        ident = (self.model_identifier or "").lower()
        if not ident:
            return False
        return any(keyword in ident for keyword in _SMALL_FALLBACK_MODEL_KEYWORDS)

    def get_available_tools(self) -> dict:
        """Filter tools based on fallback mode"""
        if getattr(self.state, "is_fallback_mode_active", False):
            filtered = {
                name: schema
                for name, schema in self.all_tools.items()
                if name in FALLBACK_ALLOWED_TOOLS
            }
            if "final_answer" in FALLBACK_ALLOWED_TOOLS and "final_answer" not in filtered:
                filtered["final_answer"] = {
                    "description": "Terminate task and return final answer to the user.",
                    "required": {"answer": str},
                    "optional": {},
                }
            return filtered
        return self.all_tools

    def _build_critique(self, result: Any, _last_tool_call: Any = None) -> str:
        findings_str = str(getattr(result, "findings", result))
        if "technical anchors" in findings_str:
            return (
                f"[VERIFIER CRITIQUE L1]: {findings_str} "
                f"Your current basis contains no textual evidence. "
                f"You must first call file_system.read or shell, "
                f"then quote a line verbatim from the output in your reply. "
                f"No claims are allowed without a quotation."
            )
        if "enumeration" in findings_str:
            return f"[VERIFIER CRITIQUE]: You claimed a number without evidence. Use the tool then state the output."

        return f"[VERIFIER CRITIQUE]: {findings_str}. Correct your approach and retry with the correct tool."

    def _format_tools_for_prompt(self) -> str:
        """Render the available tool schemas as a compact plain-text block.

        Small/fallback models (ORCA-FLASH) do not understand OpenAI-style
        ``tools`` arrays; they need the tool list inline in the system prompt
        with explicit names + args so they emit the correct JSON tool call.
        """
        tools = self.get_available_tools()
        if not tools:
            return ""
        lines = ["## AVAILABLE TOOLS (call one per turn via JSON):"]
        for name, schema in tools.items():
            if name == "final_answer":
                lines.append(f'- {name}: args={{"answer": str}}')
                continue
            required = schema.get("required", {})
            optional = schema.get("optional", {})
            req_str = ", ".join(f"{k}: {_type_name(v)}" for k, v in required.items())
            opt_str = ", ".join(f"{k}: {_type_name(v)}" for k, v in optional.items())
            spec = f"required={{ {req_str} }}" if req_str else "required={{}}"
            if opt_str:
                spec += f", optional={{ {opt_str} }}"
            lines.append(f"- {name}: {spec}")
        return "\n".join(lines)

    # ── Phase4.1 Auto-Critical Policy helpers ──────────────────────────────

    def _flag_latest_evidence_critical(self) -> None:
        """Freeze the most-recent evidence record as Critical (no-op if none)."""
        recs = self.evidence_log.get_records()
        if recs:
            self.evidence_log.flag_critical(recs[-1].evidence_id)

    def _auto_critical_from_claim(self, claim: str) -> None:
        """Trigger (a): freeze any evidence E-id explicitly cited in *claim*.

        The verifier rejected *claim* for citing missing/insufficient anchors;
        those anchors are exactly what the correction loop must keep. Freezing them
        prevents the compaction window from evicting the cited evidence mid-fix.
        """
        import re as _re
        for m in _re.finditer(r"\b(E-\d+)\b", str(claim or "")):
            self.evidence_log.flag_critical(m.group(1))


    @staticmethod
    def _summarize_it(it: "_ToolInteraction") -> str:
        """Strict-schema 1-line summary for an aged-out tool turn."""
        status = "OK" if it.ok else "FAIL"
        return (
            f"  Step {it.step}: {it.tool} → {status} (exit {it.exit_code}) "
            f"[{it.path_hint}] — {it.summary}"
        )

    # ── Phase D: Unified read counter (single source of truth) ─────────────

    # ── Phase C: Extract file suggestions from listing evidence ─────────────

    def _note_provider_failure(self, err: str) -> _LoopSignal:
        """Increment the provider fail streak, activate fallback restrictions, and terminate on threshold."""
        self._provider_fail_streak += 1
        self.state.provider_fail_streak = self._provider_fail_streak
        preview = str(err)[:200]
        bus.emit(
            "provider_failed",
            {
                "error": preview,
                "streak": self._provider_fail_streak,
                "step": self.state.step_count,
            },
        )
        if self._provider_fail_streak >= 2 and not getattr(self.state, "is_fallback_mode_active", False):
            self.state.is_fallback_mode_active = True
            bus.emit("fallback_mode_activated", {
                "streak": self._provider_fail_streak,
                "allowed_tools": sorted(FALLBACK_ALLOWED_TOOLS)
            })

        if self._provider_fail_streak >= MAX_PROVIDER_FAIL_STREAK:
            msg = "[Error: Connection lost. Exiting cleanly to protect context.]"
            self.state.update_status("FAILED")
            ctx_prompt = self._ctx.user_prompt if self._ctx else ""
            safe_msg = self._get_fallback_reason(
                ctx_prompt,
                f"Connection lost or repeated provider failure after {self._provider_fail_streak} attempts: {preview}",
            )
            bus.emit(
                "loop_completed",
                {"reason": "connection_lost", "output": safe_msg or msg},
            )
            return _LoopSignal.TERMINATE
        return _LoopSignal.CONTINUE

    def _note_provider_success(self) -> None:
        """Reset the provider fail streak upon receiving valid non-empty model text."""
        if self._provider_fail_streak > 0 or getattr(self.state, "provider_fail_streak", 0) > 0:
            self._provider_fail_streak = 0
            self.state.provider_fail_streak = 0
            if getattr(self.state, "is_fallback_mode_active", False):
                self.state.is_fallback_mode_active = False
                bus.emit("fallback_mode_deactivated")

    # SAFETY: _invoke_llm_and_normalize is intentionally NOT extracted to a
    # separate _llm_mixin.py / _llm.py (attempted + rejected in v2, re-verified
    # in v3). CONCRETE COUPLING EVIDENCE (grep-verified against live source):
    #   * SOLE WRITER of self._force_tool          -> set at L417/L424, cleared L530
    #   * SOLE WRITER of self._synthesis_directive_injected -> L456 (set), L476 (set)
    #   * SOLE WRITER of self._synthesis_directive_text     -> L457
    #   * SOLE WRITER of self._force_read_directive_text     -> L432/L444, cleared L486
    #   * READER of self._force_final (set by Fixation Breaker in run/_run_once at
    #     L747/L1047/L1070/L1119/L1138/L1161/L1490) -> read at L515 to pin tool_choice.
    # These 5 flags form the live >=3-reads convergence handshake: the method both
    # raises (_force_tool / synthesis directives) AND consumes (_force_final) the
    # control signals that gate the loop. It additionally depends on >=8 private
    # instance members (_ctx, _real_reads(), _compact_messages(), _inject_runtime_context(),
    # _logger, llm_provider, state, POLL_DELAY) plus 6 module-level helpers
    # (_prompt_requires_investigation, _has_active_goal, _resolve_default_provider,
    # _normalize_response, _extract_listing_files, bus). Extracting to a mixin would
    # either (a) force moving the 5 flags + their remote writers into the mixin
    # (shattering the convergence protocol across two files), or (b) leave 10+ fragile
    # cross-file self._ reads that break the >=3-reads gate. Per the tighten-coupling
    # rule, keep it co-located with the protocol it drives. Loop stays 1608 lines
    # (realistic lower bound; forcing <1400 would require the unsafe split above).
    def _invoke_llm_and_normalize(self) -> tuple[str, str]:
        """Invoke the LLM provider and strip formatting / forbidden thought prefixes.

        Returns ``(response_text, normalized_resp)`` where ``response_text`` is the
        raw stripped response and ``normalized_resp`` has the leading "Thought for
        Ns" prefix removed (used by the repetition fingerprint guard).
        """
        # ── Streaming path (NEW, P0 of token-level SSE) ────────────────────
        # Attempt live token streaming via the router's generate_token_stream ONLY
        # when using the default provider. If the caller provided a custom or mock
        # llm_provider (e.g. in unit tests), skip directly to the non-streaming path.
        # On ANY failure, fall through SILENTLY to the existing non-streaming
        # path below — zero UX regression. The non-streaming code is unchanged.
        if not getattr(self, "_no_stream", False) and self.llm_provider is _resolve_default_provider():
            try:
                return self._invoke_with_token_stream()
            except Exception:
                pass  # silent fallback to non-streaming

        # ── Phase D: set _force_tool based on unified read counter ───────────
        # Check at every LLM call start: if investigation is needed and reads < 3,
        # force the model to call a tool via tool_choice="required".
        # Uses _real_reads() as single source of truth.
        # Phase D: set _force_tool based on unified read counter.
        # Phase F: when reads >= 3, inject one-time synthesis directive.
        self._force_tool = False
        if self._ctx is not None:
            _needs = _prompt_requires_investigation(
                self._ctx.user_prompt, has_active_goal=_has_active_goal(self)
            )
            if _needs:
                if self._real_reads() < 3:
                    self._force_tool = True
                    # Phase G: proactive real-file directive. As soon as a listing
                    # exists, feed the model concrete EXISTING paths on EVERY forced
                    # turn so it never guesses/hallucinates paths in its first plan.
                    # Saved here, injected AFTER compaction (mirrors Phase F) so the
                    # sliding-window drop cannot swallow it.
                    _proactive_sugg = self._extract_listing_files()
                    if _proactive_sugg:
                        self._force_read_directive_text = (
                            "[CONTROL] You have not read enough source files yet "
                            "(need >=3). Do NOT guess or invent file paths. Call "
                            "file_system with action='read' on these EXISTING "
                            f"files now: {_proactive_sugg}"
                        )
                    else:
                        # Phase G+: no listing captured yet (e.g. step 1). Without a
                        # concrete file list the CONTROL injection at the call site is
                        # skipped, so the model spins thought-only rounds until the
                        # consecutive-reasoning cap aborts with zero tool output.
                        # Force a hard first action: list the target, then read.
                        self._force_read_directive_text = (
                            "[CONTROL] You have read 0 source files. Do NOT answer "
                            "from memory or reasoning alone. Your NEXT response MUST "
                            "be a tool call: use file_system with action='list' on the "
                            "target directory to discover real files, then read >=3 of "
                            "them before answering."
                        )
                # Phase F: one-time synthesis directive when reads just reached >= 3
                # Save the text; actual injection into compacted happens AFTER
                # _compact_messages + _inject_runtime_context to avoid being
                # dropped by the sliding-window compaction.
                if self._real_reads() >= 3 and not getattr(self, "_synthesis_directive_injected", False):
                    self._synthesis_directive_injected = True
                    self._synthesis_directive_text = (
                        "[CONTROL] SYNTHESIS DIRECTIVE: You have read at least 3 source files. "
                        "This is sufficient. Do NOT call any more tools. "
                        "Synthesize your architectural report IMMEDIATELY using final_answer."
                    )

        bus.emit("llm_request_started", {"step": self.state.step_count})

        compacted = self._compact_messages(self.state.get_messages())
        if compacted and compacted[0].get("role") == "system":
            compacted = self._inject_runtime_context(compacted)
        # Phase F: inject one-time synthesis directive into compacted
        # (after compaction so it survives the sliding-window drop).
        if getattr(self, "_synthesis_directive_injected", False) and hasattr(self, "_synthesis_directive_text"):
            compacted.append({
                "role": "system",
                "content": self._synthesis_directive_text,
            })
            # Prevent re-injection on subsequent iterations.
            self._synthesis_directive_injected = True
            del self._synthesis_directive_text
        # Phase G: inject proactive real-file directive (after compaction so it
        # survives the sliding-window drop). Re-derived each forced turn.
        if getattr(self, "_force_tool", False) and getattr(self, "_force_read_directive_text", ""):
            compacted.append({
                "role": "system",
                "content": self._force_read_directive_text,
            })
            # One-shot: clear so a stale directive can't linger past this call.
            self._force_read_directive_text = ""

        try:
            started = time.perf_counter()
            # Pass the run's logger to the provider so router fallback messages
            # land in the session log file instead of polluting the REPL. Only
            # forward it when using the default router entry point; custom
            # providers that don't accept **kwargs keep working untouched.
            if self.llm_provider is _resolve_default_provider():
                _fc_tools = None
                try:
                    from core.fc_schemas import build_openai_tools
                    from engine.tool_registry import registry as _fc_registry

                    # The Orchestrator is forbidden from calling execute_shell
                    # (security gate blocks it); exclude it from the FC schema so
                    # the model can never emit a blocked call via native FC.
                    _fc_tools = build_openai_tools(_fc_registry, exclude={"execute_shell"})
                except Exception:
                    _fc_tools = None
                if _fc_tools:
                    # Fixation Breaker raised _force_final (repeated call detected
                    # on a small model that ignores prose). Pin tool_choice to
                    # final_answer so the model is FORCED to emit the report
                    # instead of looping — the only reliable stop with flash models.
                    # Phase C: when _force_tool is True (reads < 3, investigation
                    # active), force the model to call A tool via "required" —
                    # it cannot emit final_answer or prose without reading.
                    _tool_choice = "auto"
                    if getattr(self, "_force_final", False):
                        _tool_choice = {"type": "function", "function": {"name": "final_answer"}}
                    elif getattr(self, "_force_tool", False):
                        _tool_choice = "required"
                    response = self.llm_provider(
                        compacted, logger=self._logger, tools=_fc_tools, tool_choice=_tool_choice
                    )
                else:
                    response = self.llm_provider(compacted, logger=self._logger)
            else:
                response = self.llm_provider(compacted)
            # Phase C: after any successful LLM call, reset _force_tool so next
            # iteration uses default tool_choice ("auto"). Placed OUTSIDE the
            # if _fc_tools branch so it runs even when native FC is unavailable.
            if getattr(self, "_force_tool", False):
                self._force_tool = False
            elapsed = time.perf_counter() - started
        # The LLM provider / router can raise a variety of errors when every
        # backend fails (e.g. llm_router raises RuntimeError("All failed: ..."),
        # or the OpenRouter/NVIDIA clients raise HTTP / auth / rate-limit
        # errors). Catch broadly so each failure is routed through
        # _note_provider_failure — which emits a visible "connection_lost"
        # message via loop_completed once the streak is exhausted — instead of
        # leaking as an unhandled exception that the REPL swallows silently.
        except (TimeoutError, ConnectionError, OSError, RuntimeError, ValueError) as exc:
            if self._note_provider_failure(f"{type(exc).__name__}: {exc}") is _LoopSignal.TERMINATE:
                return "", ""
            time.sleep(self.POLL_DELAY)
            return "", ""

        response_text = response.strip()
        try:
            _parser_debug_logger.debug(
                '\n===== RAW @ step %s =====\n%s',
                getattr(self.state, 'step_count', '?'), response_text[:3000],
            )
        except Exception:
            pass

        # Prompt Leak Detector: check if raw model response leaked structural system markers
        _LEAK_MARKERS = (
            "## TODO Discipline",
            "<hard_rules>",
            "<system_instructions>",
            "<system_identity>",
            "CRITICAL RULE:",
            "TASK CLASSIFICATION",
            "SMALL-TALK & CHIT-CHAT PROTOCOL",
        )
        if any(marker in response_text for marker in _LEAK_MARKERS):
            leak_preview = response_text[:200]
            if self._note_provider_failure(f"Prompt Leak detected: {leak_preview}") is _LoopSignal.TERMINATE:
                return "", ""
            time.sleep(self.POLL_DELAY)
            return "", ""

        normalized_resp = _normalize_response(response_text)

        if not response_text:
            bus.emit(
                "ui_validation_failed",
                {"error": "LLM returned an empty response.", "step": self.state.step_count},
            )
            self.state.append_message(
                {
                    "role": "system",
                    "content": "Your previous response was empty. Please provide either a tool call or your answer.",
                }
            )
            self.state.increment_step()
            time.sleep(self.POLL_DELAY)
            return response_text, normalized_resp

        self._note_provider_success()
        self.state.append_message({"role": "assistant", "content": response})
        bus.emit(
            "llm_request_completed",
            {"duration": elapsed, "length": len(response)},
        )
        return response_text, normalized_resp

    def _invoke_with_token_stream(self) -> tuple[str, str]:
        """Stream tokens live, return assembled response tuple.

        Mirrors the non-streaming ``_invoke_llm_and_normalize`` message assembly
        (compaction + runtime-context injection) but feeds deltas to the renderer
        and EventBus as they arrive. Returns the same ``(response_text,
        normalized_resp)`` shape. Raises on failure so the caller can fall back
        to the non-streaming path.
        """
        from core.sanitize import sanitize
        from engine.loop import _normalize_response
        from llm_router import router as _router

        bus.emit("llm_request_started", {"step": self.state.step_count})

        compacted = self._compact_messages(self.state.get_messages())
        if compacted and compacted[0].get("role") == "system":
            compacted = self._inject_runtime_context(compacted)

        collected: list[str] = []

        def display(token_text: str) -> None:
            """Fire-and-forget: render token, never raise."""
            collected.append(token_text)
            try:
                # Reuse the existing llm_token subscriber in main.py's wire_events,
                # which renders via renderer.stream_chunk under lock.
                bus.emit("llm_token", {"token": token_text})
            except Exception:
                pass

        # Cancellation: a Ctrl+C / /cancel raises the shared token. Clear it
        # before every generation so a stale flag from a previous turn can't
        # abort a fresh request. The check below honors it mid-stream.
        from core.cancellation import CancelToken

        cancel = CancelToken()
        cancel.clear()

        for delta in _router.generate_token_stream(compacted, logger=self._logger):
            if cancel.is_cancelled():
                break
            if "content" in delta and delta["content"]:
                display(delta["content"])

        response_text = "".join(collected)
        # Never raise to the user — return the partial response (per hard rule).
        if cancel.is_cancelled():
            response_text += "\n\n[⏹️ Generation cancelled]"
            cancel.clear()
        response_text = response_text.strip()
        normalized_resp = _normalize_response(response_text)

        if not response_text:
            raise RuntimeError("Streaming returned an empty response.")

        self._note_provider_success()
        self.state.append_message({"role": "assistant", "content": response_text})
        bus.emit(
            "llm_request_completed",
            {"duration": 0.0, "length": len(response_text)},
        )
        return response_text, normalized_resp


    def _check_repetition_guard(self, response_text: str, normalized_resp: str) -> _LoopSignal:
        """Abort on 'thinking-only' responses or infinite replication loops.

        Emits ``loop_completed`` with ``reason="thought_only_loop"`` or
        ``reason="infinite_replication_loop"`` and returns ``TERMINATE`` when the
        corresponding guard trips. Otherwise returns ``PROCEED``.
        """
        ctx = self._ctx
        assert ctx is not None
        has_tool = bool(extract_json_from_response(response_text))
        is_thought_only = (not has_tool) and _is_thought_only(response_text)

        if is_thought_only:
            self.state.update_status("COMPLETED")
            safe_msg = self._get_fallback_reason(
                ctx.user_prompt,
                "CRITICAL: Detected only 'Thinking' blocks without tools (bullet/star detected). "
                "Aborting loop to prevent hallucination.",
            )
            bus.emit("loop_completed", {"reason": "thought_only_loop", "output": safe_msg})
            return _LoopSignal.TERMINATE

        fingerprint = normalized_resp[:200]
        if fingerprint:
            # Check the PRE-APPEND count so the guard trips on the 3rd identical
            # response (the fingerprint has already been seen twice). This gives
            # the no-tool verifier room to defer to this guard for pure
            # reasoning loops that never emit a tool.
            if ctx.fingerprints.count(fingerprint) >= 2:
                self.state.update_status("COMPLETED")
                safe_msg = self._get_fallback_reason(
                    ctx.user_prompt,
                    "CRITICAL: Infinite Replication Loop Detected (Entropy = 0). "
                    "Aborting session to preserve API budget and memory.",
                )
                bus.emit("loop_completed", {"reason": "infinite_replication_loop", "output": safe_msg})
                return _LoopSignal.TERMINATE
            ctx.fingerprints.append(fingerprint)
            if len(ctx.fingerprints) > 3:
                ctx.fingerprints.pop(0)
        return _LoopSignal.PROCEED

    def _get_fallback_reason(self, prompt: str, fallback_reason: str) -> str:
        """Return the fallback termination reason. Performs NO cleanup — the name
        signals intent only (kept for the safe-shutdown emission paths)."""
        return fallback_reason

    def _evaluate_goal_exit(self) -> bool:
        """Check if current goal's success criteria are met"""
        goal = getattr(self.state, "active_goal", None) if hasattr(self, "state") and self.state else getattr(self, "_goal", None)
        if not goal or not getattr(goal, "success_criteria", None) or getattr(goal, "success_criteria", None) == "None":
            return True  # No criteria = no gate

        ev = getattr(self, "_evidence", None) or getattr(self, "evidence_log", None)
        if ev and hasattr(ev, "verify_fresh"):
            try:
                res = ev.verify_fresh(goal.success_criteria, {})
                if isinstance(res, bool):
                    return res
                if hasattr(res, "ok"):
                    return bool(res.ok)
                return True
            except TypeError:
                try:
                    res = ev.verify_fresh(require_tools=True, claim=goal.success_criteria)
                    if isinstance(res, bool):
                        return res
                    if hasattr(res, "ok"):
                        return bool(res.ok)
                    return True
                except Exception:
                    return False
            except Exception:
                return False
        return True

    def _handle_cycle_and_security(self, tool_call: ToolCall) -> _LoopSignal:
        """Detect repeated/oscillating tool calls and enforce the shell security gate.

        Returns ``CONTINUE`` when a cycle is detected or a shell command is
        rejected (the offending call is skipped). On pass, updates the recent-call
        tracker and returns ``PROCEED`` with ``self._active_tool`` set.
        """
        ctx = self._ctx
        assert ctx is not None
        tool_name = tool_call.tool
        tool_args = tool_call.args

        # final_answer is a termination convention, not an executable tool. When
        # a small/fallback model emits it in loose ReAct prose ("FINAL_ANSWER
        # ...") the forgiving parser surfaces it as a ToolCall here; short-circuit
        # to a clean termination instead of dispatching a non-registered tool
        # (which would be rejected and loop forever). Run the verifier inline so
        # the evidence-rejection side effects (increment count + inject [CONTROL])
        # stay synchronous — unit tests (test_evidence_feedback_loop_soft_interception)
        # depend on this; _run_once centralizes only the raw-JSON final_answer path
        # (signal FINAL_ANSWER from _parse_and_validate_tool).
        if tool_name == "final_answer":
            answer = ""
            if isinstance(tool_args, dict):
                answer = tool_args.get("answer") or tool_args.get("text") or ""
            if answer:
                self._last_response = answer
            return self._verify_claim_or_self_correct()

        # ── Fixation Breaker (Hard Stop -> force final_answer) ──────────────
        # The small Orchestrator model cycles through a ROTATION of distinct
        # calls (list ., read pyproject, list ., read main.py, list core, ...)
        # that never repeat CONSECUTIVELY — so a "last == current" comparison
        # never fires. Instead we track the SET of all executed signatures and
        # count redundant (already-seen) calls, plus a sufficiency threshold on
        # successful reads. Either condition forces final_answer on the next
        # turn (tool_choice is pinned in _invoke_llm_and_normalize), breaking
        # the non-converging loop without waiting for the step budget.
        import json as _json
        current_sig = f"{tool_name}:{_json.dumps(tool_args, sort_keys=True, ensure_ascii=False)}"
        if not hasattr(self, "_executed_sigs"):
            self._executed_sigs, self._redundant_count = set(), 0
        if current_sig in self._executed_sigs:
            self._redundant_count += 1
        else:
            self._executed_sigs.add(current_sig)

        # Phase G+: do NOT let the investigation terminate before the agent has
        # collected enough evidence. Only force final_answer once >=3 distinct
        # source files have actually been read. Below that threshold, redirect to
        # a DIFFERENT file instead of ending the loop.
        if self._redundant_count >= 2 and self._real_reads() < 3:
            suggestions = self._extract_listing_files()
            bus.emit("ui_repeated_tool", {"tool": tool_name, "step": self.state.step_count})
            self.state.append_message(
                {
                    "role": "user",
                    "content": (
                        "[CONTROL] You have already inspected this file. Read a "
                        "DIFFERENT file that has not been inspected yet. Use: "
                        f"file_system(action=\"read\"). Suggested files: "
                        f"{suggestions}. Do not reread files. Before producing a "
                        "repository-level conclusion you must inspect at least "
                        "THREE distinct source files."
                    ),
                }
            )
            self.state.increment_step()
            self._redundant_count = 0
            self._executed_sigs.clear()
            time.sleep(self.POLL_DELAY)
            return _LoopSignal.CONTINUE

        if self._redundant_count >= 2 or self._real_reads() >= 5:
            self._force_final = True
            bus.emit("ui_repeated_tool", {"tool": tool_name, "step": self.state.step_count})
            return _LoopSignal.CONTINUE

        recent_slice = list(self._recent_calls)[-4:]
        if tool_call == ctx.last_command or tool_call in recent_slice:
            ctx.repeated += 1
            self._fixation_count += 1
            if ctx.repeated >= 2 or (tool_call == ctx.last_command and ctx.repeated >= 1):
                bus.emit("ui_repeated_tool", {"tool": tool_name, "step": self.state.step_count})
                _critique_sugg = self._extract_listing_files()
                self.state.append_message(
                    {
                        "role": "user",
                        "content": (
                            f"[SYSTEM CRITIQUE] STOP! You have already executed '{tool_name}' with these exact "
                            "arguments recently. Do NOT repeat failed commands or oscillate between "
                            "them. Inspect files directly instead of trying a different strategy. "
                            f"Suggested files to read next: {_critique_sugg}"
                        ),
                    }
                )
                self.state.increment_step()
                time.sleep(self.POLL_DELAY)
                return _LoopSignal.CONTINUE
        else:
            ctx.repeated = 0

        self._recent_calls.append(tool_call)
        ctx.last_command = tool_call

        if tool_name == "execute_shell":
            command = tool_args.get("command", "")
            if not is_safe_command(command):
                bus.emit("ui_security_blocked", {"command": command, "step": self.state.step_count})
                bus.emit("tool_security_blocked", {"command": command, "step": self.state.step_count})
                bus.emit("tool_auth_violation", {
                    "role": "ORCHESTRATOR",
                    "tool": tool_name,
                    "error": "shell command violated security policy",
                })
                # Phase4.1 Auto-Critical (b): a security denial/block is frozen.
                self._flag_latest_evidence_critical()
                self.state.append_message(
                    {
                        "role": "system",
                        "content": "Your shell command violated security policy. Generate a safer alternative.",
                    }
                )
                self.state.increment_step()
                time.sleep(self.POLL_DELAY)
                return _LoopSignal.CONTINUE

            # Interactive permission gate (human-in-the-loop). The agent executes
            # on a worker thread (asyncio.to_thread), so a blocking bridge prompt
            # here never freezes the async REPL event loop. Approved commands are
            # cached in the per-run session allowlist to avoid prompt exhaustion.
            # Phase2.1: a 60s non-blocking timeout (select on stdin) fails
            # closed — auto-denying instead of hanging a Termux session.
            approved = self._request_shell_approval(command, timeout=60.0)
            if approved is False:
                bus.emit("ui_security_blocked", {"command": command, "step": self.state.step_count})
                bus.emit("tool_security_blocked", {"command": command, "step": self.state.step_count})
                # Phase4.1 Auto-Critical (b): explicit user denial is frozen.
                self._flag_latest_evidence_critical()
                warned = self._approval_timed_out
                self.state.append_message(
                    {
                        "role": "system",
                        "content": (
                            "<security_warning>Execution auto-denied (Timeout after 60s)."
                            "</security_warning>"
                            if warned else
                            "<security_warning>Execution denied by user.</security_warning>"
                        ),
                    }
                )
                self.state.increment_step()
                time.sleep(self.POLL_DELAY)
                return _LoopSignal.CONTINUE

        self._active_tool = tool_call
        return _LoopSignal.PROCEED

    def _request_shell_approval(self, command: str, timeout: float | None = None) -> bool:
        """Intercept shell execution and ask the operator to allow/deny.

        Returns ``True`` if the command is approved (cached for the session),
        ``False`` if denied, timed out, or if the input channel is
        unavailable/fails. The bridge is fail-closed: any read error or
        non-``y`` reply denies.

        Phase2.1: ``timeout`` (seconds) is forwarded to the bridge, which
        enforces it via a non-blocking ``select`` on stdin. A timeout yields
        the ``_TIMEOUT_REPLY`` sentinel (still a deny) so the caller can
        emit a distinct auto-deny warning instead of a user-deny one.

        Phase5 (Permissions): BEFORE showing the interactive prompt, the
        PermissionEngine evaluates the cascading trust hierarchy against
        ``state.shell_permissions``. An ALLOW skips the prompt entirely (silent
        auto-approval log); a DENY auto-rejects. Only ASK falls through to the
        60s interactive gate. The Phase 2.1 advanced heuristics inside the
        engine ALWAYS run first, so ``/allow *`` can never weaken obfuscation
        defenses.
        """
        ctx = self._ctx
        assert ctx is not None
        if command in ctx.approved_shell:
            return True

        # Phase5 (Permissions): cascading trust evaluation.
        decision, reason = PermissionEngine.evaluate(command, self.state.shell_permissions)
        if decision is PermissionDecision.ALLOW:
            # Silent auto-approval — MUST NOT touch the live status line so the
            # KineticStateEngine never flickers. Emitted as a structured,
            # non-interactive security log the renderer can consume quietly.
            bus.emit("security_log", {"level": "info", "message": f"Auto-approved by policy: {command}"})
            ctx.approved_shell.add(command)
            return True
        if decision is PermissionDecision.DENY:
            # Auto-reject by policy (distinct from a heuristic block or a user
            # denial). Always runs AFTER the non-overridable Phase 2.1 sweep, so
            # an obfuscated payload is still caught there first.
            bus.emit("security_log", {"level": "warn", "message": f"Auto-denied by policy: {command} ({reason})"})
            bus.emit("ui_security_blocked", {"command": command, "step": self.state.step_count})
            bus.emit("tool_security_blocked", {"command": command, "step": self.state.step_count})
            self._approval_timed_out = False
            self.state.append_message(
                {
                    "role": "system",
                    "content": f"<security_warning>Execution denied by permission policy: {command}.</security_warning>",
                }
            )
            self.state.increment_step()
            time.sleep(self.POLL_DELAY)
            return False

        # ASK — no rule matched → fall back to the existing interactive gate.
        self._approval_timed_out = False
        try:
            bridge = get_bridge()
            reply = bridge.request_user_input(
                f"[SECURITY] Requesting shell execution: {command} -> Allow? (y/n): ",
                timeout=timeout,
            ).strip().lower()
        except Exception:
            # Bridge unreachable → fail closed.
            return False

        if reply == _TIMEOUT_REPLY:
            # Distinct sentinel so the caller emits the timeout warning.
            self._approval_timed_out = True
            return False

        if reply in ("y", "yes"):
            ctx.approved_shell.add(command)
            return True
        return False

    def _build_tool_feedback(
        self, result: Any, tool_name: str, tool_args: dict[str, Any], output: str
    ) -> str:
        """Compose the user-facing feedback message for a dispatched tool call."""
        if getattr(result, "success", False):
            return f"[{tool_name} Output]\n{output}"

        guidance = ""
        if "can't open file" in output and "python" in str(tool_args):
            guidance = (
                "\n[CRITICAL HINT] To execute inline Python statements via bash, you MUST use "
                'python3 -c "import ...". Never write unflagged \'python import ...\'.'
            )
        elif any(msg in output.lower() for msg in ("timed out after", "timeoutexpired", "command execution timed out")):
            guidance = (
                "\n[CRITICAL HINT] Execution timed out waiting for input or EOF. "
                "Never execute interactive REPL scripts directly."
            )
        return (
            f"[{tool_name} Error]\n{output}\n{guidance}\n"
            "Please analyze the error and fix your command or strategy."
        )

    def _is_answer_in_hand_or_goal_met(self) -> bool:
        """Check if the evidence gathered so far satisfies the active goal or user prompt.

        When true ('بوّابة الجواب في اليد'), the loop immediately forces a final
        report instead of continuing to dispatch exploration tools (`execute_shell`,
        directory scans) or waiting for the budget ceiling.
        """
        ctx = self._ctx
        if ctx is None:
            return False

        # If a GoalSpec is active, delegate to the authoritative evaluator.
        if _has_active_goal(self):
            if self._goal and getattr(self._goal, "is_met", False):
                return True
            try:
                from core.evidence import evaluate_goal_exit
                res = evaluate_goal_exit(self._goal, self.evidence_log, require_tools=True)
                if getattr(res, "ok", False):
                    if self._goal:
                        self._goal.is_met = True
                    return True
            except Exception:
                pass
            return False

        # Without an active GoalSpec, check if targeted read/check prompts are answered
        # by existing successful evidence records.
        records = [r for r in self.evidence_log.get_records() if r.success and getattr(r, "output_snippet", "")]
        if not records:
            return False

        prompt_lower = (ctx.user_prompt or "").strip().lower()
        for rec in records:
            tool = getattr(rec, "tool", "")
            cmd_or_path = getattr(rec, "command_or_path", "") or ""
            action = getattr(rec, "action", "") or ""
            if tool == "file_system" and cmd_or_path and action in ("read", "edit", ""):
                path_str = str(cmd_or_path).strip().lower()
                if path_str and path_str not in (".", "/", ""):
                    # If the exact path read is mentioned in the prompt (e.g. pyproject.toml),
                    # we already have the requested file contents in evidence!
                    if path_str in prompt_lower:
                        return True
                    # Or if prompt asks to read/inspect/check a file and we have at least 1 successful file read.
                    if any(w in prompt_lower for w in ("read ", "check ", "inspect ", "show ", "cat ", "name ")):
                        import os as _os
                        base = _os.path.basename(path_str)
                        if base and len(base) > 2 and base in prompt_lower:
                            return True

        return False

    def _pre_dispatch_guard(self, tool_call: ToolCall) -> "ToolResult | None":
        """Phase 4.5 cheap pre-checks that short-circuit a real tool dispatch.

        Returns a ``ToolResult`` when the call should be answered WITHOUT
        consuming a real tool execution (and therefore without spending budget
        on a redundant/external call). Returns ``None`` when the call should
        proceed to the normal dispatcher path.

        Guards:
          1. file_system path jail — reject reads/writes outside the pinned
             workspace root before the tool ever runs (no wasted tool call).
          2. web_search dedup — if the normalized query was already executed
             this run, return the cached result instead of re-calling the net.
        """
        ctx = self._ctx
        assert ctx is not None
        tool_name = tool_call.tool
        tool_args = tool_call.args

        # ── Guard 1: file_system workspace jail (pre-dispatch) ───────────────
        if tool_name == "file_system" and isinstance(tool_args, dict):
            path = tool_args.get("path")
            action = (tool_args.get("action") or "").lower()
            if path and action in ("read", "write", "append", "replace", "delete"):
                from core.kernel.security import _validate_path
                if not _validate_path(str(path)):
                    bus.emit("tool_security_blocked", {
                        "command": f"file_system.{action}({path})",
                        "step": self.state.step_count,
                    })
                    return ToolResult(
                        success=False,
                        stderr=(
                            f"Access outside the workspace is forbidden. "
                            f"Path '{path}' resolves outside the pinned workspace root. "
                            f"Use a path relative to the workspace."
                        ),
                        returncode=-1,
                        status="error",
                    )

        # ── Guard 2: web_search dedup (return cached result) ────────────────
        if tool_name == "web_search" and isinstance(tool_args, dict):
            raw_query = tool_args.get("query")
            if raw_query:
                norm = str(raw_query).strip().lower()
                if norm in ctx.executed_search_queries and norm in ctx.last_search_cache:
                    bus.emit("tool_dedup_hit", {
                        "tool": "web_search",
                        "query": raw_query,
                        "step": self.state.step_count,
                    })
                    return ToolResult(
                        success=True,
                        stdout=ctx.last_search_cache[norm],
                        returncode=0,
                        status="success",
                        metadata={"deduped": True},
                    )

        # ── Guard 3: Answer-in-hand / redundant exploration guard ────────────
        # If the target file requested by the user has already been read into
        # evidence, or if the model attempts to re-read/list the directory tree (path='.')
        # after gathering successful reads, block the call and force final_answer.
        if self._is_answer_in_hand_or_goal_met():
            self._force_final = True
            if tool_name in ("file_system", "execute_shell", "web_search", "search_knowledge_base"):
                bus.emit("tool_security_blocked", {
                    "command": f"{tool_name}({tool_args}) blocked: answer in hand",
                    "step": self.state.step_count,
                })
                return ToolResult(
                    success=True,
                    stdout=(
                        "[SYSTEM DIRECTIVE] Sufficient evidence has already been gathered to answer the user's prompt. "
                        f"Do NOT execute more commands or scan directories. Immediately output your answer using: "
                        '{"tool": "final_answer", "args": {"answer": "<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"answer_in_hand_blocked": True},
                )

        if tool_name == "file_system" and isinstance(tool_args, dict):
            path = str(tool_args.get("path") or "").strip().lower()
            action = str(tool_args.get("action") or "").strip().lower()
            has_reads = any(r.success and getattr(r, "tool", "") == "file_system" and str(getattr(r, "command_or_path", "")).strip().lower() not in (".", "/", "") for r in self.evidence_log.get_records())
            if has_reads and (path in (".", "/", "") or action == "list" or any(str(r.command_or_path).strip().lower() == path for r in self.evidence_log.get_records() if r.success)):
                self._force_final = True
                return ToolResult(
                    success=True,
                    stdout=(
                        f"[SYSTEM DIRECTIVE] You already read the target files ({path or '.'}). Do NOT list directories or re-read files. "
                        'Immediately output {"tool": "final_answer", "args": {"answer": "<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"redundant_read_blocked": True},
                )

        # ── Guard 4: Re-read / wider-scope barrier (no new justification) ────
        # Point 3 of the convergence fix: a successful read of a source must not
        # be repeated, nor may a wider-scope listing (path='.' or '/') be issued
        # after a targeted read, unless a NEW explicit justification exists. This
        # is the hard backstop that independent of is_answer_in_hand keeps the
        # loop from re-touching already-read evidence.
        if tool_name == "file_system" and isinstance(tool_args, dict):
            action = str(tool_args.get("action") or "").lower()
            path = str(tool_args.get("path") or "").strip()
            path_l = path.lower()
            reads = [
                r for r in self.evidence_log.get_records()
                if getattr(r, "success", False) and getattr(r, "tool", "") == "file_system"
            ]
            read_paths = {
                str(getattr(r, "command_or_path", "")).strip().lower() for r in reads
            }
            recursive = str(tool_args.get("recursive", "")).lower() in ("true", "1", "yes")
            is_root_list = path_l in (".", "/", "") and action == "list"
            is_whole_tree_scan = is_root_list and recursive
            # Phase 0 root fix — UNIFIED EXPLORATION CONTRACT.
            # Guard 4 and the Structural Verifier (check_investigation_gates)
            # must agree on what counts as "real exploration progress". The
            # verifier requires: directories>=1, configuration>=1,
            # (entrypoints>=1 OR modules>=1), files>=3. Guard 4 therefore
            # PERMITS directed exploration that can satisfy those gates and
            # ONLY blocks the pathological pattern:
            #   (a) recursive whole-tree scan of '.'/'/'  → the exact "801-entry
            #       tree wipe" loop;
            #   (b) a SECOND non-recursive root listing (one discovery pass is
            #       enough — directories>=1 is met by the first);
            #   (c) re-reading an already-read exact file path.
            # A single non-recursive `list .` is ALLOWED exactly once so the
            # model can produce directories>=1; targeted `list <dir>` and every
            # fresh file read are always allowed. This removes the deadlock
            # where the guard blocked the very listing the verifier demanded.
            if is_whole_tree_scan:
                self._force_final = True
                return ToolResult(
                    success=True,
                    stdout=(
                        "[SYSTEM DIRECTIVE] A recursive whole-tree listing is not needed to answer this prompt. "
                        "Use a single non-recursive directory listing plus targeted file_system reads of specific files. "
                        'Immediately output {"tool": "final_answer", "args": {"answer": "<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"whole_tree_scan_blocked": True},
                )
            if is_root_list:
                # Permit exactly ONE non-recursive root listing, and only as a
                # discovery pass BEFORE any file has been read. Once the model
                # has read evidence, re-listing the root is redundant (it cannot
                # produce new files) and must be blocked — this is what keeps
                # the verifier's "files >= 3 reads" gate authoritative.
                if ctx.root_list_count >= 1 or read_paths:
                    self._force_final = True
                    return ToolResult(
                        success=True,
                        stdout=(
                            "[SYSTEM DIRECTIVE] The repository root was already listed (or you already have reads). "
                            "Do NOT re-list directories. Use targeted file_system reads of specific files. "
                            'Immediately output {"tool": "final_answer", "args": {"answer": "<your concise report from the evidence>"}}'
                        ),
                        returncode=0,
                        status="success",
                        metadata={"root_list_repeat_blocked": True},
                    )
                ctx.root_list_count += 1
                # Allowed: first non-recursive root listing (satisfies the
                # verifier's directories>=1 gate). Fall through to dispatch.
                return None
            # Targeted listing of a specific subdirectory is always allowed
            # (produces directories / modules for the verifier).
            if action == "list":
                return None
            # Re-read of an already-read exact path (action read/replace/append
            # on the same file) → block and force final.
            if action in ("read", "replace", "append", "delete", "") and path_l in read_paths:
                self._force_final = True
                return ToolResult(
                    success=True,
                    stdout=(
                        f"[SYSTEM DIRECTIVE] The file '{path}' was already read into evidence this run. "
                        "Do NOT re-read it. Immediately output your answer using: "
                        '{"tool": "final_answer", "args": {"answer": "<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"reread_blocked": True},
                )

        return None

    def _inject_guard_directive(self, pre: "ToolResult") -> None:
        """Deliver a pre-dispatch guard directive to the model WITHOUT leaking it.

        Channel-separation contract (Phase 0 root fix):
          (a) PERSISTENCE — the directive is NEVER recorded in evidence_log /
              output_snippet. Evidence = real tool outputs only.
          (b) DELIVERY — it reaches the model as a control message (role "user"
              tagged "[CONTROL]"), never disguised as a "[TOOL RESULT: ...]"
              artifact that the model would re-narrate as raw evidence.

        The guard keeps steering model behavior (convergence intact); only the
        leak path is removed.
        """
        directive = getattr(pre, "stdout", "") or getattr(pre, "stderr", "") or ""
        if directive:
            self.state.append_message({
                "role": "user",
                "content": f"[CONTROL] {directive}",
            })

    def _dispatch_and_record_evidence(self, tool_call: ToolCall) -> None:
        """Dispatch the validated tool and log the outcome to the EvidenceLog.

        Records the evidence trace, builds the user-facing feedback message,
        appends it to state, increments the step, prunes history, and sleeps for
        ``POLL_DELAY``. No return value: this is the terminal action of a
        successful iteration.
        """
        tool_name = tool_call.tool
        tool_args = tool_call.args

        # ── Consent Loop (Phase 2 Public Release Protocol) ────────────────────
        # Intercept BEFORE the dispatcher invokes the tool. The consent policy is
        # centralized in ConsentManager and is the ONLY place that decides whether
        # a tool needs approval. A declined call returns a normal successful
        # ToolResult (success=True, stdout="Execution blocked by user.") — this is
        # a valid outcome, NOT an engine error: no exception, no loop abort,
        # no loop_error emit. The LLM receives the observation and adapts.
        if ConsentManager().requires_confirmation(tool_name, tool_args):
            blocked = ConsentManager().confirm(tool_name, tool_args)
            if blocked is not None:
                result = blocked
                blocked_rec = self.evidence_log.record(
                    tool=tool_name,
                    command_or_path=_extract_cmd_or_path(tool_args),
                    success=blocked.success,
                    output_snippet=blocked.stdout or blocked.stderr,
                )
                # --- Safe Telemetry Injection (Blocked Tool) ---
                _sys_logger = getattr(self, "logger", None) or getattr(self, "_logger", None)
                if _sys_logger is None and hasattr(self, "context"):
                    _sys_logger = getattr(self.context, "logger", None)
                elif _sys_logger is None and hasattr(self, "ctx"):
                    _sys_logger = getattr(self.ctx, "logger", None)
                elif _sys_logger is None and hasattr(self, "_ctx") and self._ctx is not None:
                    _sys_logger = getattr(self._ctx, "logger", None)

                if _sys_logger and hasattr(_sys_logger, "log_execution"):
                    _sys_logger.log_execution({
                        "session_id": getattr(self.state, "session_id", "unknown"),
                        "step": getattr(self.state, "step_count", 0),
                        "type": "TOOL_EXECUTION_BLOCKED",
                        "evidence_id": getattr(blocked_rec, "evidence_id", ""),
                        "tool": tool_name,
                        "command_or_path": str(tool_args)[:100],
                        "success": blocked.success,
                        "output_snippet": truncate(blocked.stdout or blocked.stderr or "", 200),
                    })
                # -------------------------------------------------
                output = truncate(blocked.output or "", self.max_output_len)
                feedback = self._build_tool_feedback(result, tool_name, tool_args, output)
                self.state.append_message({
                    "role": "system",
                    "content": f"[TOOL RESULT: {tool_name}]\n{feedback}",
                })
                self.state.increment_step()
                time.sleep(self.POLL_DELAY)
                return

        # ── Edit Gateway (Phase 2.4) Human-in-the-Loop ────────────────────────
        # Block the engine thread and wait for human approval before applying
        # any file write/edit operation to disk. The UI receives a
        # threading.Event and a decision_box dict; it sets decision_box["approved"]
        # and calls event.set() when the operator responds to the approval prompt.
        _is_write = False
        if tool_name in ("edit_file", "replace_file_content"):
            _is_write = True
        elif tool_name == "file_system":
            _action = (tool_args or {}).get("action", "") if isinstance(tool_args, dict) else ""
            # All actions except read/list/empty are potentially destructive.
            if _action not in ("", "read", "list", "view"):
                _is_write = True

        if _is_write:
            _bridge = get_bridge()
            _approval_event = threading.Event()
            _decision_box: dict[str, bool] = {"approved": False}
            _file_path = str(tool_args.get("path") or tool_args.get("file", ""))
            _diff = str(tool_args.get("content") or tool_args.get("diff", ""))

            _bridge.emit("edit_proposed",
                file=_file_path,
                diff=_diff,
                event=_approval_event,
                decision_box=_decision_box,
            )
            _bridge.emit("status_update", message="⏳ Waiting for human approval to apply edits...")

            # FREEZE the engine thread until the operator responds (120s timeout).
            _approval_event.wait(timeout=120)

            if not _decision_box.get("approved", False):
                _bridge.emit("status_update", message="✋ Edit rejected by user.")
                _result = ToolResult(
                    success=True,
                    stdout="USER REJECTED THE EDIT. Manual override. Please revise your approach.",
                    stderr="",
                    output="USER REJECTED THE EDIT. Manual override. Please revise your approach.",
                )
                _rec = self.evidence_log.record(
                    tool=tool_name,
                    command_or_path=_extract_cmd_or_path(tool_args),
                    success=True,
                    output_snippet="Edit rejected by user",
                    action=str(tool_args.get("action", "")) if isinstance(tool_args, dict) else "",
                )
                _output = truncate(_result.output or "", self.max_output_len)
                _feedback = self._build_tool_feedback(_result, tool_name, tool_args, _output)
                self.state.append_message({
                    "role": "system",
                    "content": f"[TOOL RESULT: {tool_name}]\n{_feedback}",
                })
                self.state.increment_step()
                time.sleep(self.POLL_DELAY)
                return

            _bridge.emit("status_update", message="✅ Edit approved. Applying to disk...")

        if tool_name == "todo_write" and isinstance(tool_args, dict) and tool_args.get("action") == "update":
            from engine.tool_registry import registry
            _todo_tool = registry.get_tool("todo_write")
            _mgr = getattr(_todo_tool, "_manager", None) or getattr(_todo_tool, "todo_manager", None)
            if _mgr is None and hasattr(self, "context") and hasattr(self.context, "todo_manager"):
                _mgr = self.context.todo_manager
            if _mgr is None or len(_mgr.all()) == 0:
                result = ToolResult(
                    success=False,
                    stdout="",
                    stderr="Protocol error: call todo_write(action='plan', items=[...]) first.",
                    returncode=-1,
                )
            else:
                result = self.dispatcher.dispatch(tool_name, tool_args)
        else:
            result = self.dispatcher.dispatch(tool_name, tool_args)

        cmd_summary = _extract_cmd_or_path(tool_args)
        rec = self.evidence_log.record(
            tool=tool_name,
            command_or_path=cmd_summary,
            success=getattr(result, "success", False),
            output_snippet=getattr(result, "output", "") or getattr(result, "stderr", ""),
            action=str(tool_args.get("action", "")) if isinstance(tool_args, dict) else "",
        )
        # ── Phase F: (diagnostic tokens removed) ────────────────────────
        # ── Phase F: (PHASE_E diagnostic tokens removed) ─────────────────
        # --- Safe Telemetry Injection ---
        _sys_logger = getattr(self, "logger", None) or getattr(self, "_logger", None)
        if _sys_logger is None and hasattr(self, "context"):
            _sys_logger = getattr(self.context, "logger", None)
        elif _sys_logger is None and hasattr(self, "ctx"):
            _sys_logger = getattr(self.ctx, "logger", None)
        elif _sys_logger is None and hasattr(self, "_ctx") and self._ctx is not None:
            _sys_logger = getattr(self._ctx, "logger", None)

        if _sys_logger and hasattr(_sys_logger, "log_execution"):
            _sys_logger.log_execution({
                "session_id": getattr(self.state, "session_id", "unknown"),
                "step": getattr(self.state, "step_count", 0),
                "type": "TOOL_EXECUTION",
                "evidence_id": getattr(rec, "evidence_id", ""),
                "tool": tool_name,
                "command_or_path": cmd_summary,
                "success": getattr(result, "success", False),
                "output_snippet": truncate(getattr(result, "output", "") or getattr(result, "stderr", "") or "", 200),
            })
        # ---------------------------------

        output_val = getattr(result, "output", "") or getattr(result, "stderr", "") or str(result)
        output = truncate(output_val, self.max_output_len)

        # Phase4: append a compact interaction record driving the sliding window.
        # The latest evidence record carries the critical flag for freezing.
        ctx = self._ctx
        if ctx is not None:
            rec = self.evidence_log.get_records()[-1] if self.evidence_log.get_records() else None
            ok = bool(getattr(result, "success", False))
            exit_code = int(getattr(result, "returncode", 0) or 0)
            ctx.tool_interactions.append(_ToolInteraction(
                step=self.state.step_count,
                tool=tool_name,
                ok=ok,
                exit_code=exit_code,
                path_hint=(cmd_summary or "")[:80],
                summary=(
                    f"{'SUCCESS' if ok else 'FAILURE'}: "
                    f"{cmd_summary}".strip()
                ),
                output=output,
                evidence_id=rec.evidence_id if rec else "",
                critical=bool(rec.critical) if rec else False,
            ))

        feedback = self._build_tool_feedback(result, tool_name, tool_args, output)
        self.state.append_message({
            "role": "system",
            "content": f"[TOOL RESULT: {tool_name}]\n{feedback}",
        })
        # Phase 4.5 — web_search dedup bookkeeping: cache the executed query so
        # an identical re-issue later in the run returns the cached result.
        if tool_name == "web_search" and isinstance(tool_args, dict):
            raw_query = tool_args.get("query")
            if raw_query:
                norm = str(raw_query).strip().lower()
                if norm not in ctx.executed_search_queries:
                    ctx.executed_search_queries.append(norm)
                if getattr(result, "success", False):
                    ctx.last_search_cache[norm] = output
        # Phase 4.5 — a real dispatch occurred → reset the no-tool counter.
        if ctx is not None:
            ctx.consecutive_no_tool_rounds = 0
        self.state.increment_step()
        self.state.prune_history()
        time.sleep(self.POLL_DELAY)

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self, user_prompt: str) -> str:
        """Start the autonomous execution loop (thin orchestrator).

        Per-iteration responsibilities are delegated to the private helpers above.
        All external event names, state mutations, and the two-call
        update_state lifecycle are preserved byte-for-byte.
        """
        self.state.append_message({"role": "user", "content": user_prompt})
        self.state.update_status("RUNNING")
        bus.emit("loop_started", {"session_id": self.state.session_id})

        interrupted = False
        self._ctx = _LoopCtx(user_prompt=user_prompt)
        # Phase F: reset synthesis directive flag per run.
        self._synthesis_directive_injected = False
        # Scratch holders written by helpers, read by the orchestrator.
        self._last_response: str = ""
        self._active_tool: Optional[ToolCall] = None

        # Phase5 (GoalSpec): a ``/goal`` command initializes the active verifiable
        # objective. It is parsed here and stored centrally on RuntimeState (and
        # mirrored on the loop) so the Verifier can enforce it at exit time. The
        # raw prompt is still appended as a normal user message below so the LLM
        # sees the task, but the *objective* now additionally carries explicit,
        # checkable success criteria.
        parsed_goal = parse_goal_command(user_prompt)
        if parsed_goal is not None:
            self._goal = parsed_goal
            self.state.active_goal = parsed_goal
            bus.emit("goal_set", {
                "raw_prompt": parsed_goal.raw_prompt,
                "success_criteria": parsed_goal.success_criteria,
                "session_id": self.state.session_id,
            })

        # Phase5 (Workspace Context): load project-specific instructions from the
        # cwd once per run. Fail-safe — returns "" if no AGENTS.md/.agents/config.md
        # exists or is unreadable. Injected into messages[0] (the system anchor)
        # so Phase 4 compaction hard-preserves it and never drops it.
        self._workspace_context = load_workspace_context(Path.cwd())

        # Phase 3 (tech-debt fix): build the per-run static context ONCE here
        # (AGENT.md + skills + taste) so _inject_runtime_context never re-reads
        # them from disk on every LLM call.
        self._static_context_cache = self._build_static_context()

        try:
            while self.state.status == "RUNNING" and self.state.is_loop_safe():
                self._run_once()
        except KeyboardInterrupt:
            self.state.update_status("PAUSED")
            interrupted = True
            bus.emit("loop_interrupted", {})
        except Exception as exc:
            self.state.update_status("ERROR")
            bus.emit("loop_error", {"step": self.state.step_count, "error": str(exc)})
            raise
        finally:
            self._finalize_loop(interrupted)
            # Drop the per-run static context so it cannot leak across runs.
            self._static_context_cache = None
        return self._last_response

    def _prepare_iteration_and_check_guards(self) -> _LoopSignal:
        if self._check_budget_and_guards() is _LoopSignal.TERMINATE:
            return _LoopSignal.TERMINATE

        if self._maybe_force_partial_answer():
            return _LoopSignal.TERMINATE

        if hasattr(self, "_compactor") and self._compactor.should_compact(self.state.messages):
            self.state.messages = self._compactor.compact(
                self.state.messages,
                self.state,
                getattr(self, "evidence_log", None) or getattr(self, "_evidence", None)
            )
            bus.emit("context_compacted", {
                "messages_after": len(self.state.messages),
                "tokens_saved_estimate": self._estimate_tokens_saved()
            })

        self._maybe_auto_trigger_rag()

        if self._is_answer_in_hand_or_goal_met():
            self._force_final = True

        return _LoopSignal.CONTINUE

    def _handle_tool_signal(self, tool_call: Any, signal: _LoopSignal) -> bool:
        if signal is _LoopSignal.CONTINUE or tool_call is None:
            ctx = self._ctx
            if ctx is not None:
                ctx.consecutive_no_tool_rounds += 1
                ctx.total_no_tool_rounds += 1
            if signal is not _LoopSignal.CONTINUE and self._verify_claim_or_self_correct() is _LoopSignal.TERMINATE:
                return True
            if self._maybe_force_partial_answer():
                return True
            return True

        if signal in (_LoopSignal.TERMINATE, _LoopSignal.FINAL_ANSWER):
            if self._verify_claim_or_self_correct() is _LoopSignal.TERMINATE:
                return True
            if self._maybe_force_partial_answer():
                return True
            return True

        return False

    def _execute_tool_iteration(self, tool_call: Any, bridge: Any) -> None:
        sig = self._handle_cycle_and_security(tool_call)
        if sig is _LoopSignal.CONTINUE:
            ctx = self._ctx
            if ctx is not None:
                ctx.consecutive_no_tool_rounds += 1
                ctx.total_no_tool_rounds += 1
                if self._maybe_force_partial_answer():
                    return
            return
        if sig is _LoopSignal.TERMINATE:
            return

        pre = self._pre_dispatch_guard(tool_call)
        if pre is not None:
            self._inject_guard_directive(pre)
            self.state.increment_step()
            self.state.prune_history()
            time.sleep(self.POLL_DELAY)
            return

        self._active_tool = tool_call
        if tool_call.tool in ("file_system", "edit_file", "replace_file_content"):
            bridge.emit("edit_proposed", file=tool_call.args.get("path") or tool_call.args.get("file", ""), diff=tool_call.args.get("content") or tool_call.args.get("diff", ""))
        self._dispatch_and_record_evidence(tool_call)
        bridge.emit("status_update", message=f"Cycle completed. Step: {self.state.step_count}")

    def _run_once(self) -> None:
        """Execute a single loop iteration, delegating to the extracted helpers."""
        if self._prepare_iteration_and_check_guards() is _LoopSignal.TERMINATE:
            return

        response_text, normalized_resp = self._invoke_llm_and_normalize()
        if not response_text:
            return

        if self._check_repetition_guard(response_text, normalized_resp) is _LoopSignal.TERMINATE:
            return

        self._last_response = response_text
        bridge = get_bridge()
        bridge.emit("on_agent_thought", content=response_text)

        tool_call, signal = self._parse_and_validate_tool(response_text)
        if self._handle_tool_signal(tool_call, signal):
            return

        self._execute_tool_iteration(tool_call, bridge)


    def _finalize_loop(self, interrupted: bool) -> None:
        """Emit the terminal loop events once the iteration cycle has ended."""
        if not interrupted:
            if self.state.status == "RUNNING" and not self.state.is_loop_safe():
                self.state.update_status("PAUSED")
                bus.emit("loop_max_steps_reached", {"max_steps": self.state.max_steps})
            # Phase4.1 Auto-Critical (c): a clean completion means the final
            # successful tool artifact matches the root task — freeze it as the
            # canonical Critical Evidence so an LMK resume keeps the answer anchor.
            if self.state.status in ("COMPLETED", "COMPLETED"):
                self._flag_latest_success_evidence_critical()
            bus.emit("loop_finished", {"status": self.state.status, "steps": self.state.step_count})

    def _flag_latest_success_evidence_critical(self) -> None:
        """Freeze the most-recent *successful* evidence record as Critical."""
        for rec in reversed(self.evidence_log.get_records()):
            if rec.success:
                self.evidence_log.flag_critical(rec.evidence_id)
                return

    def _estimate_tokens_saved(self) -> int:
        """Rough token savings estimate"""
        before = sum(len(str(m.get("content", ""))) for m in self.state.messages)
        after = sum(len(json.dumps(m)) for m in self.state.messages)
        return max(0, (before - after) // 4)
