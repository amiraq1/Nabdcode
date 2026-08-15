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
from engine._loop_types import _LoopSignal, _ToolInteraction, _LoopCtx, _LEAK_MARKERS
from engine._loop_types import TOOL_FEWSHOT_FALLBACK
from engine._context import _ContextMixin
from engine._budget import _BudgetMixin
from engine._convergence import _ConvergenceMixin
from engine._tool_runner import _ToolRunnerMixin
from engine._dispatch import _ToolDispatchMixin
from core.permissions import PermissionEngine, PermissionDecision
from core.turn_outcome import TurnStatus, TurnOutcome, LLMInvocationStatus, LLMInvocationResult
from core.turn_finalizer import TurnFinalizer

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
    filter_tools_for_turn,
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
    redact_leak_preview,
)


class ToolRequiredError(RuntimeError):
    """Raised when the agent answered without using required tools."""
    pass




class ExecutionLoop(_ContextMixin, _BudgetMixin, _ConvergenceMixin, _ToolRunnerMixin, _ToolDispatchMixin):
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
        todo_manager: Any = None,
        logger: Any = None,
        model_identifier: str | None = None,
        no_stream: bool = False,
        exact_action_mode: bool = False,
        consent_manager: Any | None = None,
        tool_registry: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:

        self.state = state
        # NBD-05: one injected ConsentManager drives the whole loop; tests
        # inject a prompt function instead of env/stdin hacks.
        self.consent_manager = consent_manager or ConsentManager()
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        # Dependency Injection: the dispatcher is injected (or built lazily) so
        # engine.loop never needs a module-level import of engine.dispatcher.
        self.dispatcher = dispatcher or _build_dispatcher(state, tool_registry=tool_registry, event_bus=event_bus)
        self.llm_provider = llm_provider or _resolve_default_provider()
        self._verifier_provider = verifier_provider or _resolve_default_verifier()
        self._verifier_calls = 0  # step6: per-run budget for independent checker
        self.max_output_len = max_output_len
        self._recent_calls: deque[ToolCall] = deque(maxlen=16)
        self.evidence_log = evidence_log or EvidenceLog()
        # Convergence gate: optional TodoManager for can_finalize checks.
        self.todo_manager = todo_manager
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
        # Phase 2.C: exact-action mode — when True, only execute_shell is
        # allowed, max_tool_calls=1, TODOs disabled, consent required.
        self._exact_action_mode: bool = exact_action_mode
        # Phase 2.C: tool dispatch counter for max_tool_calls enforcement.
        self._exact_action_tool_count: int = 0
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
        # Phase 3: turn-finalization scratch holders — initialized early for
        # testability (tests may call _finalize_loop directly without run()).
        self._last_response: str = ""
        # Phase 3: turn-finalization authority — exactly one terminal outcome
        # per started turn. Created ONCE per ExecutionLoop instance (one session).
        # Reset between turns via _turn_finalizer.reset().
        self._turn_finalizer = TurnFinalizer()


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
        """Filter tools based on fallback mode and exact-action mode.

        Phase 2.C (Exact-Action Mode):
          When ``_exact_action_mode`` is True, the model may ONLY call
          ``execute_shell`` (per ``EXACT_ACTION_ALLOWED_TOOLS`` in
          ``core/_exact_action_contract.py``). All other tools (including
          ``final_answer``) are hidden from the available set so the model
          never attempts to call them. ``final_answer`` is handled as a
          system-level control message by the Convergence Gate.
        """
        filtered = filter_tools_for_turn(
            self.all_tools,
            exact_action=getattr(self, "_exact_action_mode", False),
            restricted=getattr(self.state, "is_fallback_mode_active", False),
        )
        if (
            getattr(self.state, "is_fallback_mode_active", False)
            and "final_answer" in FALLBACK_ALLOWED_TOOLS
            and "final_answer" not in filtered
        ):
            filtered["final_answer"] = {
                "description": "Terminate task and return final answer to the user.",
                "required": {"answer": str},
                "optional": {},
            }
        return filtered

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
    def _invoke_llm_and_normalize(self) -> LLMInvocationResult:
        """Invoke the LLM provider and return a typed ``LLMInvocationResult``.

        Every exit path returns an explicit, non-ambiguous result so the
        orchestration layer can classify it as SUCCESS / EMPTY_RESPONSE /
        RETRYABLE_ERROR / FATAL_ERROR / CANCELLED without inspecting raw
        strings.  The outer _finalize_loop fallback remains only as a
        last-resort invariant guard.

        Mapping:
          SUCCESS          → normal orchestration
          EMPTY_RESPONSE   → documented retry/failure policy
          RETRYABLE_ERROR  → bounded retry via _note_provider_failure
          FATAL_ERROR      → FAILED terminal outcome
          CANCELLED        → CANCELLED terminal outcome
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
            # PATCH-CORE-UNIFIED-R3: Use ctx.intent_policy.needs_investigation
            # instead of dynamically calling _prompt_requires_investigation.
            # Invariant 8 — once SYNTHESIZE/FINALIZE begins, never return to
            # planning/collection: skip the read-forcing machinery entirely.
            if self._ctx.phase not in ("SYNTHESIZE", "FINALIZE"):
                _needs = self._ctx.intent_policy.needs_investigation if self._ctx.intent_policy else False
            else:
                _needs = False
            if _needs:
                # PATCH-CORE-UNIFIED-R3: Use minimum_reads from policy.
                _min_reads = self._ctx.intent_policy.minimum_reads if self._ctx.intent_policy else 3
                if self._real_reads() < _min_reads:
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
                            f"(need >={_min_reads}). Do NOT guess or invent file paths. Call "
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
                            "target directory to discover real files, then read >="
                            f"{_min_reads} of them before answering."
                        )
                # Phase F: one-time synthesis directive when reads just reached >= minimum
                # Save the text; actual injection into compacted happens AFTER
                # _compact_messages + _inject_runtime_context to avoid being
                # dropped by the sliding-window compaction.
                # PATCH-CORE-UNIFIED-R3: Use _min_reads instead of hardcoded 3.
                if self._real_reads() >= _min_reads and not getattr(self, "_synthesis_directive_injected", False):
                    self._synthesis_directive_injected = True
                    self._synthesis_directive_text = (
                        "[CONTROL] SYNTHESIS DIRECTIVE: You have read at least "
                        f"{_min_reads} source files. "
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

                    # In exact-action mode, execute_shell MUST be in the FC
                    # schema (it is the ONLY allowed tool) and final_answer
                    # is deliberately excluded (it is injected as a system-level
                    # control message by the Convergence Gate instead).
                    if getattr(self, "_exact_action_mode", False):
                        _exclude: set[str] = {"final_answer"}
                    elif getattr(self.state, "is_fallback_mode_active", False):
                        # Fallback mode (R-UI-1): the model must be able to call
                        # execute_shell and file_system to escape the fallback
                        # loop. Only final_answer is excluded (injected by the
                        # Convergence Gate as a system-level control message).
                        _exclude = set()
                    else:
                        # Normal mode: the Orchestrator is forbidden from
                        # calling execute_shell (security gate blocks it);
                        # exclude it from the FC schema so the model can never
                        # emit a blocked call via native FC.
                        _exclude = {"execute_shell"}
                    _fc_tools = build_openai_tools(
                        _fc_registry, exclude=_exclude,
                        allowed=list(self.get_available_tools().keys()),
                    )
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
            exc_type = type(exc).__name__
            if self._note_provider_failure(f"{exc_type}: {exc}") is _LoopSignal.TERMINATE:
                return LLMInvocationResult(
                    status=LLMInvocationStatus.FATAL_ERROR,
                    error_type=exc_type,
                    safe_message=str(exc)[:200],
                    retryable=False,
                )
            time.sleep(self.POLL_DELAY)
            return LLMInvocationResult(
                status=LLMInvocationStatus.RETRYABLE_ERROR,
                error_type=exc_type,
                safe_message=str(exc)[:200],
                retryable=True,
            )

        response_text = response.strip()
        try:
            _parser_debug_logger.debug(
                '\n===== RAW @ step %s =====\n%s',
                getattr(self.state, 'step_count', '?'), response_text[:3000],
            )
        except Exception:
            pass

        # Prompt Leak Detector: check if raw model response leaked structural system markers
        if any(marker in response_text for marker in _LEAK_MARKERS):
            leak_preview = response_text[:200]
            if self._note_provider_failure(redact_leak_preview(leak_preview)) is _LoopSignal.TERMINATE:
                return LLMInvocationResult(
                    status=LLMInvocationStatus.FATAL_ERROR,
                    error_type="PromptLeak",
                    safe_message="Model response leaked system markers",
                    retryable=False,
                )
            time.sleep(self.POLL_DELAY)
            return LLMInvocationResult(
                status=LLMInvocationStatus.RETRYABLE_ERROR,
                error_type="PromptLeak",
                safe_message="Model response leaked system markers",
                retryable=True,
            )

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
            return LLMInvocationResult(
                status=LLMInvocationStatus.EMPTY_RESPONSE,
                retryable=True,
            )

        self._note_provider_success()
        self.state.append_message({"role": "assistant", "content": response})
        bus.emit(
            "llm_request_completed",
            {"duration": elapsed, "length": len(response)},
        )
        return LLMInvocationResult(
            status=LLMInvocationStatus.SUCCESS,
            content=response_text,
        )

    def _invoke_with_token_stream(self) -> LLMInvocationResult:
        """Stream tokens live, return assembled response tuple.

        Mirrors the non-streaming ``_invoke_llm_and_normalize`` message assembly
        (compaction + runtime-context injection) but feeds deltas to the renderer
        and EventBus as they arrive. Returns the same ``(response_text,
        normalized_resp)`` shape. Raises on failure so the caller can fall back
        to the non-streaming path.
        """
        from core.sanitize import sanitize
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

        try:
            for delta in _router.generate_token_stream(compacted, logger=self._logger):
                if cancel.is_cancelled():
                    break
                if "content" in delta and delta["content"]:
                    display(delta["content"])
        except (TimeoutError, ConnectionError, OSError, RuntimeError, ValueError) as exc:
            exc_type = type(exc).__name__
            if self._note_provider_failure(f"{exc_type}: {exc}") is _LoopSignal.TERMINATE:
                return LLMInvocationResult(
                    status=LLMInvocationStatus.FATAL_ERROR,
                    error_type=exc_type,
                    safe_message=str(exc)[:200],
                    retryable=False,
                )
            time.sleep(self.POLL_DELAY)
            return LLMInvocationResult(
                status=LLMInvocationStatus.RETRYABLE_ERROR,
                error_type=exc_type,
                safe_message=str(exc)[:200],
                retryable=True,
            )

        response_text = "".join(collected)
        # Never raise to the user — return the partial response (per hard rule).
        if cancel.is_cancelled():
            response_text += "\n\n[⏹️ Generation cancelled]"
            cancel.clear()
        response_text = response_text.strip()

        # ── Streaming Leak Detector (mirrors _invoke_llm_and_normalize) ──
        if any(marker in response_text for marker in _LEAK_MARKERS):
            leak_preview = response_text[:200]
            if self._note_provider_failure(redact_leak_preview(leak_preview)) is _LoopSignal.TERMINATE:
                return LLMInvocationResult(
                    status=LLMInvocationStatus.FATAL_ERROR,
                    error_type="PromptLeak",
                    retryable=False,
                )
            time.sleep(self.POLL_DELAY)
            return LLMInvocationResult(
                status=LLMInvocationStatus.RETRYABLE_ERROR,
                error_type="PromptLeak",
                retryable=True,
            )

        if not response_text:
            return LLMInvocationResult(
                status=LLMInvocationStatus.EMPTY_RESPONSE,
                error_type="EmptyResponse",
                safe_message="Streaming returned an empty response.",
                retryable=True,
            )

        self._note_provider_success()
        self.state.append_message({"role": "assistant", "content": response_text})
        bus.emit(
            "llm_request_completed",
            {"duration": 0.0, "length": len(response_text)},
        )
        return LLMInvocationResult(
            status=LLMInvocationStatus.SUCCESS,
            content=response_text,
        )


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

        # PATCH-CORE-UNIFIED-R3: Use centralized terminal outcome.
        from engine._loop_helpers import _commit_terminal_outcome

        if is_thought_only:
            safe_msg = self._get_fallback_reason(
                ctx.user_prompt,
                "CRITICAL: Detected only 'Thinking' blocks without tools (bullet/star detected). "
                "Aborting loop to prevent hallucination.",
            )
            _commit_terminal_outcome(
                self,
                status="FAILED",
                reason="thought_only_loop",
                output=safe_msg,
                fallback_msg="Thought-only loop detected.",
            )
            return _LoopSignal.TERMINATE

        fingerprint = normalized_resp[:200]
        if fingerprint:
            # Check the PRE-APPEND count so the guard trips on the 3rd identical
            # response (the fingerprint has already been seen twice). This gives
            # the no-tool verifier room to defer to this guard for pure
            # reasoning loops that never emit a tool.
            if ctx.fingerprints.count(fingerprint) >= 2:
                safe_msg = self._get_fallback_reason(
                    ctx.user_prompt,
                    "CRITICAL: Infinite Replication Loop Detected (Entropy = 0). "
                    "Aborting session to preserve API budget and memory.",
                )
                _commit_terminal_outcome(
                    self,
                    status="FAILED",
                    reason="infinite_replication_loop",
                    output=safe_msg,
                    fallback_msg="Infinite replication loop detected.",
                )
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

    # ------------------------------------------------------------------
    # _handle_cycle_and_security — decomposed into 3 focused stages
    # ------------------------------------------------------------------
    def _check_fixation_breaker(self, tool_call: ToolCall) -> _LoopSignal:
        """Stage 1: Fixation Breaker — detect redundant signatures, force final.

        Tracks the SET of all executed tool-call signatures and counts
        redundant (already-seen) calls. When the agent has repeatedly
        visited the same call without reaching 3 distinct reads, it is
        redirected to a DIFFERENT file. Once redundant >= 2 OR reads >= 5,
        ``_force_final`` is raised so the next LLM turn is pinned to
        ``final_answer`` via ``tool_choice``.
        """
        tool_name = tool_call.tool
        tool_args = tool_call.args

        import json as _json
        current_sig = f"{tool_name}:{_json.dumps(tool_args, sort_keys=True, ensure_ascii=False)}"
        if not hasattr(self, "_executed_sigs"):
            self._executed_sigs, self._redundant_count = set(), 0
        if current_sig in self._executed_sigs:
            self._redundant_count += 1
        else:
            self._executed_sigs.add(current_sig)

        # Phase G+: below 3 reads, redirect to a DIFFERENT file; never end.
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

        return _LoopSignal.PROCEED

    def _check_oscillation(self, tool_call: ToolCall) -> _LoopSignal:
        """Stage 2: Oscillation Detection — spot repeatedly-called commands.

        Compares the current call against the 4 most-recent calls and
        ``ctx.last_command``. On repeat, emits a ``[SYSTEM CRITIQUE]`` and
        returns ``CONTINUE`` (the loop re-invokes the LLM). On pass, updates
        ``ctx.last_command`` and appends the call to ``self._recent_calls``,
        returning ``PROCEED`` (fall through to shell security).
        """
        ctx = self._ctx
        assert ctx is not None
        tool_name = tool_call.tool

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
        return _LoopSignal.PROCEED

    def _check_shell_security(self, tool_call: ToolCall) -> _LoopSignal:
        """Stage 3: Shell Security Gate.

        When the tool is ``execute_shell``, validates the command against
        ``is_safe_command`` and requests interactive shell approval. On
        pass, sets ``self._active_tool`` and returns ``PROCEED``. On
        block/deny, emits telemetry and returns ``CONTINUE``.
        """
        ctx = self._ctx
        assert ctx is not None
        tool_name = tool_call.tool
        tool_args = tool_call.args

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

            # Interactive permission gate (human-in-the-loop).
            approved = self._request_shell_approval(command, timeout=60.0)
            if approved is False:
                bus.emit("ui_security_blocked", {"command": command, "step": self.state.step_count})
                bus.emit("tool_security_blocked", {"command": command, "step": self.state.step_count})
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

    def _handle_cycle_and_security(self, tool_call: ToolCall) -> _LoopSignal:
        """Detect repeated/oscillating tool calls and enforce the shell security gate.

        Dispatches to 3 focused stages in sequence. Returns ``CONTINUE`` when
        a cycle is detected or a shell command is rejected (the offending call
        is skipped). On pass, returns ``PROCEED`` with ``self._active_tool`` set.
        """
        ctx = self._ctx
        assert ctx is not None
        tool_name = tool_call.tool
        tool_args = tool_call.args

        # final_answer is a termination convention, not an executable tool.
        # Short-circuit to the verifier instead of dispatching.
        if tool_name == "final_answer":
            answer = ""
            if isinstance(tool_args, dict):
                answer = tool_args.get("answer") or tool_args.get("text") or ""
            if answer:
                self._last_response = answer
            return self._verify_claim_or_self_correct()

        # Chain 3 stages — first non-PROCEED result wins.
        for stage in (
            self._check_fixation_breaker,
            self._check_oscillation,
            self._check_shell_security,
        ):
            result = stage(tool_call)
            if result is not _LoopSignal.PROCEED:
                return result
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
            # AgentStatusBar never flickers. Emitted as a structured,
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
                # Uses the module-level engine.goal_verifier import (line 25);
                # core.evidence has no `evaluate_goal_exit` symbol (D-07).
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

    # ------------------------------------------------------------------
    # Pre-dispatch guards — 4 independent checks, each returns ToolResult | None
    # ------------------------------------------------------------------
    def _guard_path_jail(
        self, tool_name: str, tool_args: object
    ) -> "ToolResult | None":
        """Guard 1: block file_system operations outside the workspace root."""
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
        return None

    def _guard_web_dedup(
        self, tool_name: str, tool_args: object
    ) -> "ToolResult | None":
        """Guard 2: return cached web_search result for duplicate queries."""
        if tool_name == "web_search" and isinstance(tool_args, dict):
            raw_query = tool_args.get("query")
            if raw_query:
                norm = str(raw_query).strip().lower()
                ctx = self._ctx
                if ctx is not None and norm in ctx.executed_search_queries and norm in ctx.last_search_cache:
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
        return None

    def _guard_answer_in_hand(
        self, tool_name: str, tool_args: object
    ) -> "ToolResult | None":
        """Guard 3: stop exploration when sufficient evidence is gathered.

        Checks two conditions:
          (a) ``_is_answer_in_hand_or_goal_met()`` — blocks any exploration tool.
          (b) Redundant root list or re-read after at least one successful read.
        """
        # (a) Answer-in-hand / goal-met gate
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
                        "[SYSTEM DIRECTIVE] Sufficient evidence has already been gathered "
                        "to answer the user's prompt. "
                        "Do NOT execute more commands or scan directories. Immediately "
                        'output your answer using: '
                        '{"tool": "final_answer", "args": {"answer": '
                        '"<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"answer_in_hand_blocked": True},
                )

        # (b) Redundant root list / re-read after reads exist
        if tool_name == "file_system" and isinstance(tool_args, dict):
            path = str(tool_args.get("path") or "").strip().lower()
            action = str(tool_args.get("action") or "").strip().lower()
            has_reads = any(
                r.success and getattr(r, "tool", "") == "file_system"
                and str(getattr(r, "command_or_path", "")).strip().lower()
                    not in (".", "/", "")
                for r in self.evidence_log.get_records()
            )
            if has_reads and (
                path in (".", "/", "")
                or action == "list"
                or any(
                    str(r.command_or_path).strip().lower() == path
                    for r in self.evidence_log.get_records() if r.success
                )
            ):
                self._force_final = True
                return ToolResult(
                    success=True,
                    stdout=(
                        "[SYSTEM DIRECTIVE] You already read the target files "
                        f"({path or '.'}). Do NOT list directories or re-read files. "
                        'Immediately output {"tool": "final_answer", '
                        '"args": {"answer": '
                        '"<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"redundant_read_blocked": True},
                )
        return None

    def _guard_reread_barrier(
        self, tool_name: str, tool_args: object
    ) -> "ToolResult | None":
        """Guard 4: block whole-tree scans, repeated root lists, and re-reads.

        Phase 0 root fix — UNIFIED EXPLORATION CONTRACT.
        Guard 4 and the Structural Verifier (check_investigation_gates)
        must agree on what counts as "real exploration progress". The
        verifier requires: directories>=1, configuration>=1,
        (entrypoints>=1 OR modules>=1), files>=3. Guard 4 therefore
        PERMITS directed exploration that can satisfy those gates and
        ONLY blocks the pathological pattern:
          (a) recursive whole-tree scan of '.'/'/'  → the exact "801-entry
              tree wipe" loop;
          (b) a SECOND non-recursive root listing (one discovery pass is
              enough — directories>=1 is met by the first);
          (c) re-reading an already-read exact file path.
        A single non-recursive `list .` is ALLOWED exactly once so the
        model can produce directories>=1; targeted `list <dir>` and every
        fresh file read are always allowed. This removes the deadlock
        where the guard blocked the very listing the verifier demanded.
        """
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

            # (a) Recursive whole-tree scan → block
            if is_whole_tree_scan:
                self._force_final = True
                return ToolResult(
                    success=True,
                    stdout=(
                        "[SYSTEM DIRECTIVE] A recursive whole-tree listing is not "
                        "needed to answer this prompt. "
                        "Use a single non-recursive directory listing plus targeted "
                        "file_system reads of specific files. "
                        'Immediately output {"tool": "final_answer", '
                        '"args": {"answer": '
                        '"<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"whole_tree_scan_blocked": True},
                )

            # (b) Second non-recursive root listing → block
            if is_root_list:
                if self._ctx and (self._ctx.root_list_count >= 1 or read_paths):
                    self._force_final = True
                    return ToolResult(
                        success=True,
                        stdout=(
                            "[SYSTEM DIRECTIVE] The repository root was already listed "
                            "(or you already have reads). "
                            "Do NOT re-list directories. Use targeted file_system reads "
                            "of specific files. "
                            'Immediately output {"tool": "final_answer", '
                            '"args": {"answer": '
                            '"<your concise report from the evidence>"}}'
                        ),
                        returncode=0,
                        status="success",
                        metadata={"root_list_repeat_blocked": True},
                    )
                if self._ctx:
                    self._ctx.root_list_count += 1
                # First non-recursive root listing: allowed.
                return None

            # (c) Targeted subdirectory listing: always allowed
            if action == "list":
                return None

            # (d) Re-read of an already-read exact path → block
            if action in ("read", "replace", "append", "delete", "") and path_l in read_paths:
                self._force_final = True
                return ToolResult(
                    success=True,
                    stdout=(
                        f"[SYSTEM DIRECTIVE] The file '{path}' was already read into "
                        "evidence this run. "
                        "Do NOT re-read it. Immediately output your answer using: "
                        '{"tool": "final_answer", '
                        '"args": {"answer": '
                        '"<your concise report from the evidence>"}}'
                    ),
                    returncode=0,
                    status="success",
                    metadata={"reread_blocked": True},
                )
        return None

    def _guard_exact_action(
        self, tool_name: str, tool_args: object
    ) -> "ToolResult | None":
        """Guard 5: Phase 2.C exact-action mode — block non-execute_shell tools.

        When exact-action mode is active, only execute_shell is allowed.
        Any other tool is blocked pre-dispatch with a typed error.
        This runs BEFORE the other guards.
        """
        if getattr(self, "_exact_action_mode", False) and tool_name != "execute_shell":
            return ToolResult(
                success=False,
                stderr=(
                    f"[EXACT_ACTION_BLOCKED] Tool '{tool_name}' is not allowed in "
                    "exact-action mode. Only execute_shell is permitted."
                ),
                returncode=-1,
                status="blocked",
            )
        if getattr(self, "_exact_action_mode", False) and tool_name == "execute_shell":
            from core.canonicalize import canonicalize
            from core._exact_action_contract import EXACT_ACTION_PATTERNS
            
            prompt = self._ctx.user_prompt if self._ctx else ""
            if not prompt:
                return None
            
            requested = prompt
            lower_prompt = prompt.lower()
            for p in EXACT_ACTION_PATTERNS:
                if p in lower_prompt:
                    idx = lower_prompt.find(p)
                    requested = prompt[idx + len(p):].strip()
                    if requested.startswith(":"):
                        requested = requested[1:].strip()
                    break
            
            emitted = tool_args.get("command", "")
            if canonicalize(requested) != canonicalize(emitted):
                return ToolResult(
                    success=False,
                    stderr=(
                        f"[COMMAND_FIDELITY_DIVERGENCE] Emitted command diverges from requested command.\n"
                        f"Requested (canonical): {canonicalize(requested)}\n"
                        f"Emitted (canonical): {canonicalize(emitted)}"
                    ),
                    returncode=-1,
                    status="blocked",
                )

        # Phase 2.C: in exact-action mode, force consent prompt by NOT
        # caching shell approvals. Clear approved_shell at start of each
        # run so every command goes through the interactive consent gate.
        # This prevents a previously-approved command from authorizing a
        # different command in a later turn.
        return None

    def _pre_dispatch_guard(self, tool_call: ToolCall) -> "ToolResult | None":
        """Phase 4.5 cheap pre-checks that short-circuit a real tool dispatch.

        Chains 5 independent guards; the first non-None result wins.
        Guard 5 (exact-action) runs first for priority.
        Returns ``None`` when the call should proceed to the normal dispatcher.
        """
        ctx = self._ctx
        assert ctx is not None
        tool_name = tool_call.tool
        tool_args = tool_call.args

        if getattr(self.state, "is_fallback_mode_active", False):
            allowed = filter_tools_for_turn(
                self.all_tools,
                restricted=True,
            )
            if tool_name not in allowed and tool_name != "final_answer":
                return ToolResult(
                    success=False,
                    stderr=(
                        f"[FALLBACK_TOOL_BLOCKED] Tool '{tool_name}' is not allowed "
                        f"in fallback mode. Allowed tools: {sorted(allowed)}."
                    ),
                    returncode=-1,
                    status="blocked",
                    metadata={"allowed_tools": sorted(allowed)},
                )

        for guard in (
            self._guard_exact_action,
            self._guard_path_jail,
            self._guard_web_dedup,
            self._guard_answer_in_hand,
            self._guard_reread_barrier,
        ):
            result = guard(tool_name, tool_args)
            if result is not None:
                return result
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

    # NOTE: ``_dispatch_and_record_evidence`` is intentionally NOT redefined
    # in this class body. It resolves via MRO to
    # ``_ToolDispatchMixin._dispatch_and_record_evidence`` (engine/_dispatch.py),
    # which orchestrates the same 3 stages *plus* the Phase-2.A WRONG_TOOL
    # one-shot re-selection. A previous class-level copy shadowed the mixin
    # and made that re-selection branch permanently unreachable (D-08).

    def run(self, user_prompt: str) -> TurnOutcome:
        """Start the autonomous execution loop (thin orchestrator).

        Per-iteration responsibilities are delegated to the private helpers above.
        All external event names, state mutations, and the two-call
        update_state lifecycle are preserved byte-for-byte.

        Returns a TurnOutcome with the terminal result of this turn.
        """
        self.state.append_message({"role": "user", "content": user_prompt})
        self.state.update_status("RUNNING")
        bus.emit("loop_started", {"session_id": self.state.session_id})

        interrupted = False
        # PATCH-CORE-UNIFIED-R3: classify_intent EXACTLY ONCE at start, store
        # the result on _LoopCtx. Dynamic reclassification is FORBIDDEN.
        # PATCH-INTENT-ROUTING-R4: Use core.investigation.classify_intent (not
        # engine.deep_agent.classify_intent) so the result is an InvestigationIntent
        # enum value that _get_intent_policy can type-check.
        from core.investigation import classify_intent as classify_investigation_intent
        from engine._loop_helpers import _get_intent_policy, _commit_terminal_outcome
        investigation_intent = classify_investigation_intent(user_prompt)
        # PATCH-INTENT-ROUTING-R4: Graceful TypeError handling — if an invalid
        # string/type somehow reaches _get_intent_policy, route to FAILED via
        # the centralized TurnFinalizer instead of crashing with a traceback.
        try:
            _policy = _get_intent_policy(investigation_intent)
        except TypeError as _r4_err:
            from engine._loop_types import IntentPolicy
            _policy = IntentPolicy()  # safest default (all gates off)
            _commit_terminal_outcome(
                self,
                status="FAILED",
                reason="intent_classification_type_error",
                output=str(_r4_err),
                fallback_msg="Intent classification failed: invalid taxonomy type.",
            )
            return self._turn_finalizer.outcome
        # PATCH-INTENT-ROUTING-R4: For SINGLE_FILE_LOOKUP, extract the target file
        # from the user prompt and store it on the policy.
        if investigation_intent == "Single File Lookup":
            import re as _re
            # PATCH-INTENT-ROUTING-R4: Extract target path from the user prompt.
            # Handle quotes at the Python level before regex (avoids "\" in
            # raw strings) so inline quoted paths like Read "file.py" work.
            # PATCH-R4.1: Normalize path via _normalize_path() for strict
            # relative path matching. Rejects absolute and traversal paths.
            from engine._loop_helpers import _normalize_path
            _verb_match = _re.match(
                r"(?:read|view|show|cat|check|inspect)\s+", user_prompt, _re.IGNORECASE,
            )
            if _verb_match:
                _after_verb = user_prompt[_verb_match.end():]
                # Strip one leading quote if present (handles Read "file.py")
                if _after_verb and _after_verb[0] in ("'", '"'):
                    _after_verb = _after_verb[1:]
                _m = _re.search(r"([\w/\-\.]+(?:\.[a-zA-Z]\w+))", _after_verb)
                if _m:
                    _raw = _m.group(1)
                    try:
                        _policy.required_target = _normalize_path(_raw)
                    except ValueError:
                        # Traversal or absolute path — store for diagnostics
                        _policy.required_target = _raw
        self._ctx = _LoopCtx(
            user_prompt=user_prompt,
            intent=investigation_intent,
            intent_policy=_policy,
        )
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
        return self._turn_finalizer.outcome

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
            # Reasoning-only iteration (no dispatch): never progress.
            ctx = self._ctx
            if ctx is not None:
                ctx.consecutive_no_progress += 1
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
            # Guard-blocked iteration (no dispatch): never progress.
            ctx = self._ctx
            if ctx is not None:
                ctx.consecutive_no_progress += 1
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
        from core.plan_apply import task_graph_live_status

        status_message = f"Cycle completed. Step: {self.state.step_count}"
        graph_summary = task_graph_live_status(self.state)
        if graph_summary:
            status_message = f"{status_message} | {graph_summary}"
        bridge.emit("status_update", message=status_message)

        # ── Phase 2.4: Early exit after exact-action tool success ──────────
        # After a single execute_shell dispatch in exact_action_mode, use the
        # tool output as the final answer and terminate. This avoids 7-8
        # additional LLM calls (thought-only loop + investigation gate rejections)
        # that previously exhausted the budget and produced a partial answer.
        # The claim gate (test/commit spoofing) remains active via _emit_final;
        # only investigation gates (verify_fresh, read-count) are bypassed since
        # the user asked for exactly one command, not analysis.
        # Uses a dedicated post-tool reasoning counter so standard investigation
        # prompts are unaffected.
        if getattr(self, "_exact_action_mode", False):
            # Terminate directly after tool success — avoid extra LLM calls.
            # Keep ONLY the claim gate active (test/commit spoofing check).
            # Skip convergence gate (can_finalize), verify_fresh, and read-count
            # gates — the user asked for exactly one command, not analysis.
            self._post_tool_reasoning_rounds = 0
            recs = self.evidence_log.get_records()
            tool_output = ""
            if recs and recs[-1].success:
                tool_output = (recs[-1].output_snippet or "").strip()
            if tool_output:
                self._last_response = tool_output

            # Run the claim gate directly (bypasses convergence gate, verify_fresh,
            # read-count gates, but checks test/commit spoofing).
            from core.verifier import check_final_answer_claim_gate
            _gate_result = check_final_answer_claim_gate(
                tool_output, self.evidence_log
            )
            if _gate_result.passed:
                self.state.update_status("COMPLETED")
                bus.emit("loop_completed", {
                    "reason": "exact_action_complete",
                    "output": tool_output,
                })
            else:
                # Claim gate rejected — apply cap on retries
                self._post_tool_reasoning_rounds = getattr(
                    self, "_post_tool_reasoning_rounds", 0
                ) + 1
                if self._post_tool_reasoning_rounds >= 3:
                    # Hard cap: emit with [UNVERIFIED] markers
                    for u in _gate_result.unsupported_claims:
                        _tok = u.split(":")[-1].strip()
                        if _tok and _tok in tool_output:
                            tool_output = tool_output.replace(
                                _tok, f"[UNVERIFIED] {_tok}"
                            )
                    self._last_response = tool_output
                    from engine._loop_helpers import _commit_terminal_outcome
                    _commit_terminal_outcome(
                        self,
                        status="COMPLETED",
                        reason="exact_action_gate_capped",
                        output=tool_output,
                    )

    def _run_once(self) -> None:
        """Execute a single loop iteration, delegating to the extracted helpers."""
        if self._prepare_iteration_and_check_guards() is _LoopSignal.TERMINATE:
            return

        result = self._invoke_llm_and_normalize()
        if result.status is not LLMInvocationStatus.SUCCESS:
            # Non-success status is handled by the outer _finalize_loop fallback.
            return

        response_text = result.content
        normalized_resp = _normalize_response(response_text)

        if self._check_repetition_guard(response_text, normalized_resp) is _LoopSignal.TERMINATE:
            return

        # UX-10: Mechanical Tool-Enforcement
        from core.refusal_detector import is_refusal
        if is_refusal(response_text) and not any(getattr(r, "success", False) for r in self.evidence_log.get_records()):
            if getattr(self, "_refusal_retry_count", 0) < 3:
                self._refusal_retry_count = getattr(self, "_refusal_retry_count", 0) + 1
                import time
                self.state.append_message({
                    "role": "user",
                    "content": "You MUST call a tool first"
                })
                self.state.increment_step()
                time.sleep(getattr(self, "POLL_DELAY", 0.5))
                return

        self._last_response = response_text
        bridge = get_bridge()
        bridge.emit("on_agent_thought", content=response_text)

        tool_call, signal = self._parse_and_validate_tool(response_text)
        if self._handle_tool_signal(tool_call, signal):
            return

        self._execute_tool_iteration(tool_call, bridge)


    def _finalize_loop(self, interrupted: bool) -> None:
        """Emit the terminal loop events once the iteration cycle has ended.

        Phase 3: guarantees exactly one terminal TurnOutcome per started turn.
        If no outcome was finalized during the run, creates a FAILED fallback.
        The TurnFinalizer prevents overwriting an existing outcome.
        """
        # Phase 3: create terminal outcome if none was finalized during the run.
        # Uses state.status as the authoritative discriminator (not _last_response,
        # which can be a tool-call JSON from intermediate iterations).
        if not self._turn_finalizer.is_finalized:
            if self.state.status == "COMPLETED" and self._last_response:
                # Normal completion via final_answer or repetition guard
                self._turn_finalizer.finalize(TurnOutcome(
                    status=TurnStatus.COMPLETED,
                    safe_message=self._last_response,
                    final_answer=self._last_response,
                ))
            elif interrupted:
                self._turn_finalizer.finalize(TurnOutcome(
                    status=TurnStatus.FAILED,
                    safe_message="Interrupted by user",
                    failure_stage="interrupted",
                ))
            elif self.state.status == "FAILED":
                self._turn_finalizer.finalize(TurnOutcome(
                    status=TurnStatus.FAILED,
                    safe_message=self._last_response or "Loop ended with FAILED status",
                    failure_stage="terminal_failure",
                ))
            else:
                self._turn_finalizer.finalize(TurnOutcome(
                    status=TurnStatus.FAILED,
                    safe_message="Loop ended without terminal outcome",
                    failure_stage="unclassified_terminal_path",
                ))

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
