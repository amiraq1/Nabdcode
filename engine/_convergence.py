"""
_ConvergenceMixin — final answer emission, verification gate, evidence synthesis.
Extracted from engine/loop.py (refactor step5-d).
CRITICAL: _emit_final is the single choke point for ALL terminations.
"""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from core.kernel.events import bus
from core.utils import safe_strip

from engine._loop_types import _LoopSignal, _LoopCtx
from engine.goal_verifier import evaluate_goal_exit, MAX_GOAL_RETRIES

if TYPE_CHECKING:
    pass

# step6: budget for independent-checker calls per run (bounded token/time cost).
MAX_VERIFIER_CALLS: int = 2


def _parse_verifier_verdict(raw: str) -> bool | None:
    """Extract the boolean verdict from the checker's JSON response.

    Returns True (pass) / False (fail) / None (unparseable). Never raises.
    """
    if not raw:
        return None
    # Find the first {...} JSON object anywhere (flash models may prefix prose).
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    blob = raw[start : end + 1]
    try:
        data = json.loads(blob)
    except Exception:
        return None
    v = str(data.get("verdict", "")).strip().lower()
    if v == "pass":
        return True
    if v == "fail":
        return False
    return None


def _resolve_default_verifier() -> Callable[[str, str, str, Any], str]:
    """Lazily resolve the independent verifier LLM (DI seam, avoids import cycle)."""
    from llm_router import run_verifier_check
    return run_verifier_check


class _ConvergenceMixin:
    """
    Mixin للـ ExecutionLoop يحتوي نقطة الاختناق النهائية.
    يفترض: self._ctx, self.state, self.evidence_log, self._goal,
    self.POLL_DELAY, self.MAX_EVIDENCE_RETRIES, self._last_response،
    وكل التوابع الأخرى للكلاس المُدمَج.
    """

    def _real_reads(self) -> int:
        """Return count of distinct file paths successfully read via file_system read/edit or code_intelligence.

        Single source of truth for all read-counting logic. Counts each unique
        path once (distinct by lowercased path). Excludes root list ("." / "/").
        """
        seen: set[str] = set()
        for r in self.evidence_log.get_records():
            if not r.success:
                continue
            tool = getattr(r, "tool", "") or ""
            action = getattr(r, "action", "") or ""
            path = str(getattr(r, "command_or_path", "") or "").strip().lower()
            if path in (".", "/", ""):
                continue
            if tool == "file_system" and action in ("read", "edit", ""):
                seen.add(path)
            elif tool in ("code_intelligence", "secure_code_intelligence") and action in ("list_symbols", "get_definition", "find_references"):
                seen.add(path)
        return len(seen)

    def _extract_listing_files(self, max_suggestions: int = 3) -> str:
        """Extract 2-3 concrete .py file paths from the most recent listing output.

        Scans evidence records for successful ``file_system list`` calls and
        extracts .py filenames from the output snippet. Returns a comma-separated
        string like 'core/__init__.py, core/constants.py, core/config.py'.
        Falls back to the directory name + '__init__.py' when no filenames found.
        Returns empty string when listing_dir is root-level ("." or "/").
        """
        # Find the most recent listing record: match action="list" OR any
        # file_system record where command_or_path looks like a directory path
        # (no file extension, not root) — some tools may not populate action.
        listing_dir = ""
        for rec in reversed(self.evidence_log.get_records()):
            if not rec.success or rec.tool != "file_system":
                continue
            action = getattr(rec, "action", "") or ""
            cmd = str(getattr(rec, "command_or_path", "") or "").strip()
            if cmd in (".", "/", ""):
                continue
            if action == "list":
                listing_dir = cmd
                break
            # Fallback: no action field set, but command_or_path is a directory
            # (no file extension).
            if not action and "." not in cmd:
                listing_dir = cmd
                break

        if not listing_dir:
            return ""

        # Phase F: build set of already-read paths (exclude from suggestions).
        already_read = set()
        for r in self.evidence_log.get_records():
            if r.success and r.tool == "file_system":
                a = getattr(r, "action", "") or ""
                if a in ("read", "edit", ""):
                    p = str(getattr(r, "command_or_path", "") or "").strip().lower()
                    if p and p not in (".", "/", ""):
                        already_read.add(p)

        # Scan output snippets of all recent file_system records for .py files
        files: list[str] = []
        seen: set[str] = set()
        for rec in reversed(self.evidence_log.get_records()):
            if not rec.success:
                continue
            snippet = str(getattr(rec, "output_snippet", "") or "")
            # Find .py filenames in the output
            for m in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*\.py)\b', snippet):
                fname = m.group(1)
                if fname not in seen:
                    seen.add(fname)
                    # Build path: <listing_dir>/<filename>
                    _full = f"{listing_dir}/{fname}"
                    # Phase F: skip already-read paths.
                    if _full.lower() in already_read:
                        continue
                    files.append(_full)
                    if len(files) >= max_suggestions:
                        break
            if len(files) >= max_suggestions:
                break

        if files:
            return ", ".join(files)

        # Fallback: no unread .py files found — suggest directory itself.
        return f"{listing_dir}/__init__.py"

    def _build_evidence_summary(self) -> str:
        """Minimal, isolated evidence summary for the independent checker.

        Deliberately excludes the maker's reasoning chain / chat history — only
        the successful records' tool + output snippet (capped) are shown, so the
        checker judges on evidence, not on the maker's self-assessment (R3).
        """
        lines = []
        for rec in self.evidence_log.get_records():
            if rec.success and rec.output_snippet:
                snippet = rec.output_snippet[:300].strip()
                if snippet:
                    lines.append(f"- [{rec.tool}] {snippet}")
        return "\n".join(lines) if lines else "(no successful evidence collected)"

    def _run_independent_checker(self) -> bool:
        """Run the independent LLM checker over an ISOLATED context.

        Returns True if the checker accepts (pass), False if it rejects (fail).
        The checker receives ONLY {goal, final_answer, evidence_summary} — never
        the maker's full conversation memory. This is the semantic gate layered
        ON TOP of the mandatory rule-based gates (evaluate_goal_exit / reads
        gate). Bounded to MAX_VERIFIER_CALLS per run; any failure (missing
        verifier, network error, unparseable verdict) falls back to the existing
        deterministic behavior (R8) so termination never breaks.
        """
        verifier = getattr(self, "_verifier_provider", None)
        if verifier is None:
            return True  # no checker configured → don't block (fallback R8)
        budget = getattr(self, "_verifier_calls", 0)
        if budget >= MAX_VERIFIER_CALLS:
            return True  # budget exhausted → fall back to mandatory gates (R7/R8)
        self._verifier_calls = budget + 1
        try:
            goal = self._ctx.user_prompt if self._ctx is not None else ""
            answer = getattr(self, "_last_response", "") or ""
            summary = self._build_evidence_summary()
            raw = verifier(goal, answer, summary, logger=self._logger)
            verdict = _parse_verifier_verdict(raw)
            if verdict is None:
                # Unparseable → treat as pass-through (don't block on noise).
                return True
            return verdict
        except Exception as exc:  # network/timeout/provider down
            if self._logger is not None:
                try:
                    self._logger.warning(
                        f"[Verifier] independent checker failed, falling back to "
                        f"mandatory gates: {exc}"
                    )
                except Exception:
                    pass
            return True

    def _verify_claim_or_self_correct(self) -> _LoopSignal:
        """Run the L1 Structural Verifier against the final non-tool response.

        Phase5 (GoalSpec): the verifiable exit condition is checked FIRST. When
        a GoalSpec is active the generic verifier must NOT be allowed to declare
        a false "Success" — the goal gate is authoritative and re-enters the
        loop (or terminates with reason ``goal_not_met``) if its criteria are
        not proven against live evidence.
        """
        from engine._loop_helpers import _has_active_goal, _prompt_requires_investigation

        ctx = self._ctx
        assert ctx is not None
        bus.emit("ui_no_tool_call", {"step": self.state.step_count})

        # ── step6: independent LLM checker (semantic gate, layered ON TOP) ──
        # Runs ONLY at the termination decision, over an ISOLATED context
        # {goal, final_answer, evidence_summary}. If it rejects, re-enter the
        # loop with a concise critique instead of blindly emitting. The
        # mandatory rule-based gates below still apply regardless of this result.
        if not self._run_independent_checker():
            critique = (
                "[VERIFIER REJECT]: The independent checker found your final "
                "answer is not sufficiently grounded in the collected evidence. "
                "Do NOT claim completion. Re-enter the loop, gather stronger "
                "evidence (read actual source, not just listings), and address "
                "the gaps before answering."
            )
            self.state.append_message({"role": "user", "content": critique})
            bus.emit("verifier_critique", {
                "step": self.state.step_count,
                "attempt": getattr(self._ctx, "goal_correct_count", 0),
                "max_attempts": MAX_VERIFIER_CALLS,
                "critique": critique,
                "goal_blocked": True,
            })
            self.state.increment_step()
            return _LoopSignal.CONTINUE

        if self._goal is not None and self._goal.raw_prompt.strip():
            bus.emit("goal_verify", {
                "session_id": self.state.session_id,
                "raw_prompt": self._goal.raw_prompt,
                "step": self.state.step_count,
                "criteria_met": False,
            })
            if not getattr(self._goal, "success_criteria", None) or getattr(self._goal, "success_criteria", None) == "None":
                pass
            else:
                goal_ok = self._evaluate_goal_exit()
                goal_result = evaluate_goal_exit(
                    self._goal, self.evidence_log, require_tools=True,
                    final_claim=self._last_response,
                )
                if not goal_result.ok or not goal_ok:
                    self._auto_critical_from_claim(self._last_response)
                    if ctx.goal_correct_count < MAX_GOAL_RETRIES:
                        ctx.goal_correct_count += 1
                        ctx.fingerprints.clear()
                        self._last_tool_signature = None
                        self._fixation_count = 0
                        self._executed_sigs = set()
                        self._redundant_count = 0
                        ctx.last_command = None
                        self._recent_calls.clear()
                        critique = goal_result.to_critique() if not goal_result.ok else "Goal success criteria not proven against live evidence."
                        self.state.append_message({"role": "user", "content": critique})
                        bus.emit(
                            "verifier_critique",
                            {
                                "step": self.state.step_count,
                                "attempt": ctx.goal_correct_count,
                                "max_attempts": MAX_GOAL_RETRIES,
                                "critique": critique,
                                "goal_blocked": True,
                            },
                        )
                        self.state.increment_step()
                        backoff_delay = min(self.POLL_DELAY * (2 ** (ctx.goal_correct_count - 1)), 4.0)
                        time.sleep(backoff_delay)
                        return _LoopSignal.CONTINUE
                    self._goal.is_met = False
                    self.state.active_goal = self._goal
                    self.state.update_status("COMPLETED")
                    safe_msg = self._get_fallback_reason(
                        ctx.user_prompt,
                        "[GOAL NOT MET] " + " ".join(goal_result.findings if not goal_result.ok else ["Criteria not verified against live evidence."]),
                    )
                    bus.emit("loop_completed", {"reason": "goal_not_met", "output": safe_msg})
                    return _LoopSignal.TERMINATE

            bus.emit("goal_verify", {
                "session_id": self.state.session_id,
                "raw_prompt": self._goal.raw_prompt,
                "step": self.state.step_count,
                "criteria_met": True,
            })
            self._goal.is_met = True

        # Phase 0 convergence: verify_fresh moved to _emit_final (single choke point).
        # Check verify_fresh via _emit_final before declaring termination.
        if not self._emit_final(self._last_response, "natural_completion"):
            return _LoopSignal.CONTINUE
        return _LoopSignal.TERMINATE

    def _synthesize_from_evidence(self, reason: str) -> str:
        """Build a clean Markdown summary from the evidence gathered so far.

        Used as a safety net so the user never sees a raw tool-call JSON dumped
        as the "final answer" — every termination path funnels through
        ``_emit_final``, which falls back here when the stored response is a raw
        tool call or empty.
        """
        ctx = self._ctx
        lines = []
        for rec in reversed(self.evidence_log.get_records()):
            if rec.success and rec.output_snippet:
                snippet = rec.output_snippet[:300].strip()
                if snippet:
                    lines.append(f"- [{rec.tool}] {snippet}")
            if len(lines) >= 5:
                break
        summary = "\n".join(lines) if lines else "(no successful tool output captured yet)"
        if reason in ("answer_in_hand", "goal_satisfied", "no_tool_cap", "consecutive_reasoning_limit") and lines:
            return f"Based on the gathered evidence:\n\n{summary}"
        task = ctx.user_prompt if ctx else ""
        return (
            f"[Synthesized answer — {reason}]\n"
            f"Task: {task}\n"
            f"What I found:\n{summary}\n"
            f"(Agent stopped before a clean final_answer; summary built from collected evidence.)"
        )

    def _emit_final(self, output: str, reason: str) -> bool:
        """Single choke point for every final answer — never emits raw tool JSON.

        Phase 0 convergence: the verify_fresh gate is called INSIDE this function
        so every emission path (natural/partial/forced/shutdown) is verified.

        - No active goal: pass immediately (no reads required).
        - Active goal: require >= 3 real file reads (read action, not list).
        On rejection: inject a concise directive and return False (caller continues).
        On hard cap exceeded: emit an explicit failure message.
        On pass: emit normally.

        Returns True if emitted, False if rejected (caller should continue loop).
        """
        from engine.loop import (
            _looks_like_tool_call,
            _prompt_requires_investigation,
            _has_active_goal,
            _derive_read_hint,
        )

        if _looks_like_tool_call(output) or not safe_strip(output or ""):
            output = self._synthesize_from_evidence(reason)
            self._last_response = output

        # ── Phase 0 verify_fresh gate (single choke point) ────────────────
        ctx = self._ctx
        if ctx is not None:
            # Gate discriminator: casual chat ("hi") → pass immediately.
            # Investigation / active-goal prompts → require real reads.
            needs_verify = _prompt_requires_investigation(
                ctx.user_prompt, has_active_goal=_has_active_goal(self)
            )
            if needs_verify:
                # Phase D: unified read counter from _real_reads().
                real_reads = self._real_reads()
                # If reads >= 3, reset force_tool and let model answer freely.
                # Phase F: separate gates — reads gate + echo gate.
                # Gate 1: insufficient reads (real_reads < 3).
                # Gate 2: raw echo — model pasted a directory listing verbatim
                #   ("listing for '" or "directory listing") instead of
                #   synthesizing. "based on the gathered evidence:" is a
                #   legitimate synthesis lead-in, NOT an echo marker.
                # Combined: block if insufficient reads OR raw echo.
                _is_listing_only = real_reads < 3
                _is_echo = any(
                    m in (output or "").lower()
                    for m in ("listing for '", "directory listing")
                )
                _is_listing_only = _is_listing_only or _is_echo
                if not _is_listing_only:
                    # Sufficient reads: reset force_tool, let model emit final_answer.
                    self._force_tool = False
                else:
                    self._evidence_rejection_count += 1
                    if self._evidence_rejection_count > self.MAX_EVIDENCE_RETRIES:
                        # Hard cap exceeded: emit explicit failure, never truncated echo.
                        self._force_tool = False
                        output = (
                            f"[Convergence failed — inspected {real_reads} file(s), "
                            f"minimum required: 3. Please refine your query or "
                            f"request specific files to read.]"
                        )
                        self._last_response = output
                    else:
                        # Reject: force tool call + inject concrete file suggestions.
                        self._force_tool = True
                        # Derive file suggestions from latest listing evidence.
                        _file_suggestions = self._extract_listing_files()
                        _hint = _derive_read_hint(ctx.user_prompt)
                        if not _file_suggestions and _hint:
                            _file_suggestions = _hint.lstrip(" (e.g. ").rstrip(")")
                        if _file_suggestions:
                            _suggestion_line = (
                                f" Suggested files to read: {_file_suggestions}."
                            )
                        else:
                            # No listing captured yet (e.g. model jumped straight
                            # to a read, or this is a creation/docs task that never
                            # listed a directory). Without a concrete file list the
                            # rejection is un-actionable and the model stalls until
                            # MAX_EVIDENCE_RETRIES fires "Convergence failed". Force
                            # a hard first action: list the target, then read.
                            _suggestion_line = (
                                " No directory listing captured yet, so no specific "
                                "files can be suggested. Your NEXT response MUST be a "
                                "tool call: use file_system with action='list' on the "
                                "target directory to discover real files, then read "
                                ">=3 of them before answering."
                            )
                        rejection_msg = (
                            f"[CONTROL] FINAL_ANSWER rejected — {real_reads} file(s) read, "
                            f"minimum is 3. You MUST call file_system with action='read' to read actual "
                            f"source files.{_suggestion_line} "
                            f"Do NOT emit final_answer until you have read >=3 files."
                        )
                        self.state.append_message({"role": "user", "content": rejection_msg})
                        self.state.increment_step()
                        return False
            else:
                # No investigation needed (chitchat): reset force_tool.
                self._force_tool = False

        # ── Normal emit path ──────────────────────────────────────────────
        self.state.update_status("COMPLETED")
        bus.emit("loop_completed", {"reason": reason, "output": output})
        bus.emit("show_final_answer", {"output": output})
        return True
