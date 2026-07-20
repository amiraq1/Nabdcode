"""
_BudgetMixin — budget enforcement and soft-cap partial answer.
Extracted from engine/loop.py (refactor step5-c).
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from core.kernel.events import bus
from core.utils import safe_strip

from engine._loop_types import (
    _LoopSignal,
    _LoopCtx,
    MAX_BUDGET_SECONDS,
    MAX_BUDGET_TOKENS,
    MAX_CONSECUTIVE_NO_TOOL_ROUNDS,
    BUDGET_SOFT_WARN_RATIO,
)

if TYPE_CHECKING:
    pass


class _BudgetMixin:
    """
    Mixin للـ ExecutionLoop يحتوي حراس الميزانية.
    يفترض: self._ctx (أو ctx كمعامل)، MAX_BUDGET_SECONDS،
    MAX_BUDGET_TOKENS، MAX_SELF_CORRECT موجودة في الكلاس المُدمَج.
    """

    def _check_budget_and_guards(self) -> _LoopSignal:
        """Enforce the time/token budget ceiling and abort the loop if breached.

        Emits ``loop_completed`` with ``reason="budget_exhausted"`` and returns
        ``TERMINATE`` on breach. Otherwise returns ``PROCEED``.
        """
        from engine._loop_helpers import (
            _prompt_requires_investigation,
            _has_active_goal,
        )

        ctx = self._ctx
        assert ctx is not None
        elapsed_total = time.time() - ctx.start_time
        token_est = sum(
            len(str(m.get("content", ""))) // 4 for m in self.state.get_messages()
        )
        # Phase 0 Fix B: cumulative no-tool reasoning cap. The total counter
        # NEVER resets on transient tool calls, so it bounds non-converging
        # thought-only loops even when a small model interleaves tool calls to
        # dodge the consecutive cap.
        # Phase D: step-based hard ceiling for investigation prompts (10 cycles absolute max).
        # This is an absolute safety net — never loops forever even on small models.
        _step_hard_cap = False
        if _prompt_requires_investigation(ctx.user_prompt, has_active_goal=_has_active_goal(self)):
            # Phase F: synthesis buffer — 15-cycle ceiling when reads >= 3
            _hard_limit = 15 if self._real_reads() >= 3 else 10
            if self.state.step_count > _hard_limit:
                _step_hard_cap = True
        hard_ceiling = (
            elapsed_total > MAX_BUDGET_SECONDS
            or token_est > MAX_BUDGET_TOKENS
            or not self.state.is_loop_safe()
            or (ctx.total_no_tool_rounds > MAX_CONSECUTIVE_NO_TOOL_ROUNDS * 2 and getattr(self.state, "active_goal", None) is None)
            or _step_hard_cap
        )
        if hard_ceiling:
            if not self._maybe_force_partial_answer(force_cap=True):
                self.state.update_status("COMPLETED")
                last_resp = getattr(self, "_last_response", "")
                if not last_resp or not safe_strip(last_resp):
                    safe_msg = self._get_fallback_reason(
                        ctx.user_prompt,
                        f"Budget Ceiling: time={int(elapsed_total)}s tokens~{token_est}",
                    )
                    self._last_response = safe_msg
                if not self._emit_final(self._last_response, "budget_exhausted"):
                    return _LoopSignal.CONTINUE
            return _LoopSignal.TERMINATE
        return _LoopSignal.PROCEED

    def _maybe_force_partial_answer(self, force_cap: bool = False) -> bool:
        """Phase 4.5: near budget ceiling or consecutive reasoning cap reached, force a partial/summary answer.

        When the run has consumed >= ``BUDGET_SOFT_WARN_RATIO`` of its ceiling
        (time, tokens, or steps) OR when ``consecutive_no_tool_rounds`` exceeds
        ``MAX_CONSECUTIVE_NO_TOOL_ROUNDS`` and the model has NOT already produced a
        final answer, synthesize a partial summary from the evidence gathered so
        far and terminate cleanly — instead of dying silently at the hard cap with
        nothing shown to the user.

        Returns ``True`` if it forced termination (caller should stop).
        """
        from engine.loop import (
            _prompt_requires_investigation,
            _has_active_goal,
            _looks_like_tool_call,
            _is_thought_only,
            _extract_final_answer,
        )

        ctx = self._ctx
        assert ctx is not None
        elapsed_total = time.time() - ctx.start_time
        token_est = sum(
            len(str(m.get("content", ""))) // 4 for m in self.state.get_messages()
        )
        time_ratio = elapsed_total / MAX_BUDGET_SECONDS if MAX_BUDGET_SECONDS else 0
        token_ratio = token_est / MAX_BUDGET_TOKENS if MAX_BUDGET_TOKENS else 0
        step_ratio = self.state.step_count / self.state.max_steps if getattr(self.state, "max_steps", 0) else 0
        is_budget = max(time_ratio, token_ratio, step_ratio) >= BUDGET_SOFT_WARN_RATIO
        # The consecutive-no-tool cap is the authoritative terminator for
        # casual (no active GoalSpec) reasoning loops. When a verifiable goal
        # IS active, the GoalSpec exit gate owns termination (emitting
        # 'goal_not_met'), so the cap must yield to it instead of forcing a
        # partial answer. The discriminator is the active goal, not whether
        # evidence was gathered.
        # Phase D: suppress no-tool cap when investigation is needed AND
        # reads are making progress (increasing). This gives the model enough
        # budget to reach >=3 reads then synthesize. Cap fires only for
        # chitchat loops or stuck-investigation (reads not increasing).
        _is_making_progress = (
            _prompt_requires_investigation(ctx.user_prompt, has_active_goal=_has_active_goal(self))
            and self._real_reads() > self._last_read_count
        )
        self._last_read_count = self._real_reads()
        is_cap = (
            (ctx.consecutive_no_tool_rounds > MAX_CONSECUTIVE_NO_TOOL_ROUNDS
             or ctx.total_no_tool_rounds > MAX_CONSECUTIVE_NO_TOOL_ROUNDS * 2)
            and getattr(self.state, "active_goal", None) is None
            and not _is_making_progress
        )
        is_answer_in_hand = self._is_answer_in_hand_or_goal_met()

        # Convergence fix: a guard block (Guard 3/4) set _force_final because the
        # model already had enough evidence or tried a redundant/wider-scope call.
        # Terminate with a CLEAN answer from evidence — never the "[Partial answer"
        # banner, which is the maimed output the convergence criterion forbids.
        if getattr(self, "_force_final", False):
            _lr = getattr(self, "_last_response", "") or ""
            if _lr and not _looks_like_tool_call(_lr) and not _is_thought_only(_lr):
                if not self._emit_final(_lr, "answer_in_hand"):
                    return False
            else:
                if not self._emit_final("", "answer_in_hand"):
                    return False
            return True

        if not force_cap and not is_budget and not is_cap and not is_answer_in_hand:
            return False
        # Already terminating with a real answer — don't double-emit.
        # BUT a raw tool-call JSON left in _last_response (the loop stores every
        # model response there, including tool calls) is NOT a real answer — if
        # we skip on it, the run dumps that raw JSON as the "final answer".
        # Only suppress synthesis when _last_response is an actual report, i.e.
        # it was set by a terminating path (final_answer / no_tool_call), not by
        # the per-step assignment of a tool-call payload.
        _lr = getattr(self, "_last_response", "") or ""
        _lr_stripped = safe_strip(_lr)
        # If the stored response is already a clean final_answer extracted by the
        # terminating path, don't double-emit. But if it's leftover text/thought on
        # a consecutive no-tool cap (or budget cap), we MUST terminate cleanly instead
        # of returning False (which would loop forever).
        if _lr_stripped and _extract_final_answer(_lr) is not None:
            return False

        # Check if we have successful evidence gathered so far.
        has_evidence = any(rec.success and rec.output_snippet for rec in self.evidence_log.get_records())
        if not has_evidence and _lr_stripped and not _is_thought_only(_lr) and not _looks_like_tool_call(_lr):
            # Dify / zero-evidence casual termination: if no tools were ever called
            # and the model produced clean text that isn't just a thought block, emit
            # it directly as the final response instead of a verbose Partial banner.
            if not self._emit_final(_lr_stripped, "no_tool_cap"):
                return False
            return True

        if is_answer_in_hand or (has_evidence and _lr_stripped and not _is_thought_only(_lr) and not _looks_like_tool_call(_lr)):
            reason_str = "answer_in_hand" if is_answer_in_hand else "no_tool_cap"
            if _lr_stripped and not _is_thought_only(_lr) and not _looks_like_tool_call(_lr):
                if not self._emit_final(_lr_stripped, reason_str):
                    return False
            else:
                if not self._emit_final("", reason_str):
                    return False
            return True

        # Build a partial summary from the most-recent successful evidence.
        lines = []
        for rec in reversed(self.evidence_log.get_records()):
            if rec.success and rec.output_snippet:
                snippet = rec.output_snippet[:300].strip()
                if snippet:
                    lines.append(f"- [{rec.tool}] {snippet}")
            if len(lines) >= 5:
                break
        summary = "\n".join(lines) if lines else "(no successful tool output captured yet)"
        reason_label = "budget threshold reached" if is_budget else "consecutive reasoning limit reached"
        partial = (
            f"[Partial answer — {reason_label}]\n"
            f"Task: {ctx.user_prompt}\n"
            f"What I found so far:\n{summary}\n"
            f"(Note: the agent stopped early to avoid exhausting the budget. "
            f"Refine your question or run again for a fuller result.)"
        )
        self._last_response = partial
        self.state.update_status("COMPLETED")
        bus.emit("loop_completed", {"reason": "partial_answer_budget" if is_budget else "partial_answer_cap", "output": partial})
        bus.emit("show_final_answer", {"output": partial})
        return True
