"""Regression tests for the loop progress-accounting root fix.

The loop must NOT kill broad-but-productive tasks with "no-progress limit
reached", while still terminating genuine stalls. Invariants pinned here:

 1. reasoning-count semantics replaced by no-progress semantics
 2. only substantive new evidence resets the no-progress counter
 3. TODO updates never count as substantive progress
 4. identical TODO updates are suppressed BEFORE tool execution
 5. identical call + identical result is NOT progress
 6. new file/result/evidence IS progress
 7. the final 20% of the budget is reserved for synthesis/finalization
 8. once SYNTHESIZE begins, no return to planning
 9. hard limit emits a structured answer from collected evidence
10. never emit raw tool-call JSON merely because the budget was exhausted
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.evidence import EvidenceLog
from core.kernel.state import RuntimeState
from core.parser import ToolCall
from tools.models import ToolResult

from engine._budget import _BudgetMixin
from engine._convergence import _ConvergenceMixin
from engine._dispatch import _ToolDispatchMixin
from engine._loop_types import (
    _LoopCtx,
    _LoopSignal,
    MAX_NO_PROGRESS_STEPS,
    IntentPolicy,
)
from core.turn_finalizer import TurnFinalizer


class _SpyDispatcher:
    """Records reached dispatches; returns scripted/static ToolResults."""

    def __init__(self, result=None):
        self.calls = []
        self._result = result

    def dispatch(self, tool_name, kwargs):
        self.calls.append((tool_name, kwargs))
        if self._result is not None:
            return self._result
        return ToolResult(success=True, stdout=f"OUT:{tool_name}:{kwargs.get('path') or kwargs}")


class _ProbeLoop(_ToolDispatchMixin, _BudgetMixin, _ConvergenceMixin):
    """Real budget/dispatch/synthesis logic against fake state + dispatcher."""

    POLL_DELAY = 0

    def __init__(self, dispatcher, prompt="analyze this project", max_steps=50):
        self.state = RuntimeState(session_id="probe", max_steps=max_steps)
        self.evidence_log = EvidenceLog()
        self.max_output_len = 2000
        # PATCH-CORE-UNIFIED-R3: Use real _LoopCtx with real IntentPolicy
        self._ctx = _LoopCtx(
            user_prompt=prompt,
            intent="Repository Investigation" if "analyze" in prompt.lower() or "check" in prompt.lower() else "Chat",
            intent_policy=IntentPolicy(requires_plan=True, minimum_reads=3, needs_investigation=True),
        )
        self.dispatcher = dispatcher
        self._last_response = ""
        self._last_read_count = 0
        self._force_final = False
        self._exact_action_mode = False
        self._evidence_rejection_count = 0
        self.MAX_EVIDENCE_RETRIES = 3
        self._path_rejection_count = 0
        self._verifier_calls = 0
        self._verifier_provider = None
        self._logger = None
        self.todo_manager = None
        self._turn_finalizer = TurnFinalizer()
        self.emitted = []

    # Seams that bypass the convergence-gate/network pipeline (unit scope):
    def _build_tool_feedback(self, result, tool_name, tool_args, output):
        return output

    def _emit_final(self, output, reason):
        # PATCH-CORE-UNIFIED-R3: Route through centralized _commit_terminal_outcome
        from engine._loop_helpers import _commit_terminal_outcome
        _commit_terminal_outcome(self, status="COMPLETED", reason=reason, output=output)
        self.emitted.append((output, reason))
        return True

    def _real_reads(self):
        return 0

    def _is_answer_in_hand_or_goal_met(self):
        return False

    def _get_fallback_reason(self, prompt, context):
        return "(no answer)"

    def _get_todo_manager(self):
        return None


class TestProductiveMultiFileInspection(unittest.TestCase):
    """Invariant 1/6: distinct new reads keep a broad inspection alive."""

    def test_new_evidence_resets_counter_every_time(self):
        loop = _ProbeLoop(_SpyDispatcher())
        for i in range(6):
            loop._ctx.consecutive_no_progress += 2  # two thinking rounds
            loop._dispatch_and_record_evidence(
                ToolCall(tool="file_system", args={"action": "read", "path": f"f{i}.py"})
            )
            self.assertEqual(loop._ctx.consecutive_no_progress, 0)
            self.assertIn(loop._ctx.phase, ("PLAN", "COLLECT"))
        self.assertEqual(loop._ctx.phase, "COLLECT")
        self.assertEqual(loop._ctx.tool_call_count, 6)
        self.assertEqual(len(loop._ctx.progress_sigs), 6)


class TestDuplicateTodoSuppression(unittest.TestCase):
    """Invariants 3/4: TODO never progresses; identical TODOs never execute."""

    def test_identical_todo_update_suppressed_before_execution(self):
        spy = _SpyDispatcher()
        loop = _ProbeLoop(spy)
        plan = {"action": "plan", "items": ["survey repo", "read 3 files"]}

        loop._dispatch_and_record_evidence(ToolCall(tool="todo_write", args=plan))
        self.assertEqual(len(spy.calls), 1)  # first plan really dispatched
        self.assertEqual(loop._ctx.consecutive_no_progress, 1)  # NOT progress

        loop._dispatch_and_record_evidence(ToolCall(tool="todo_write", args=plan))
        self.assertEqual(len(spy.calls), 1)  # identical repeat suppressed pre-exec
        self.assertEqual(loop._ctx.consecutive_no_progress, 2)  # still no progress
        self.assertEqual(loop._ctx.tool_call_count, 2)


class TestDuplicateReadDetection(unittest.TestCase):
    """Invariant 5: identical tool call + identical result is not progress."""

    def test_identical_call_and_result_does_not_reset(self):
        result = ToolResult(success=True, stdout="SAME BYTES")
        spy = _SpyDispatcher(result=result)
        loop = _ProbeLoop(spy)
        call = ToolCall(tool="file_system", args={"action": "read", "path": "a.py"})

        loop._dispatch_and_record_evidence(call)
        self.assertEqual(loop._ctx.consecutive_no_progress, 0)  # first time = new

        loop._ctx.consecutive_no_progress = 2
        loop._dispatch_and_record_evidence(call)
        self.assertEqual(loop._ctx.consecutive_no_progress, 3)  # duplicate ≠ progress
        self.assertEqual(len(loop._ctx.progress_sigs), 1)

    def test_failed_dispatch_is_not_progress(self):
        spy = _SpyDispatcher(result=ToolResult(success=False, stderr="boom"))
        loop = _ProbeLoop(spy)
        loop._dispatch_and_record_evidence(
            ToolCall(tool="file_system", args={"action": "read", "path": "a.py"})
        )
        self.assertEqual(loop._ctx.consecutive_no_progress, 1)


class TestNoProgressTermination(unittest.TestCase):
    """Invariant 9: genuine stall terminates at the cap with a structured answer."""

    def test_stall_terminates_with_structured_partial(self):
        loop = _ProbeLoop(_SpyDispatcher())
        loop.evidence_log.record(tool="file_system", command_or_path="a.py",
                                 success=True, output_snippet="a.py dunder main")
        loop._ctx.consecutive_no_progress = MAX_NO_PROGRESS_STEPS
        forced = loop._maybe_force_partial_answer(force_cap=True)
        self.assertTrue(forced)
        self.assertIn("[Partial answer", loop._last_response)
        self.assertIn("no-progress limit reached", loop._last_response)
        self.assertIn("a.py dunder main", loop._last_response)


class TestFinalizationReserve(unittest.TestCase):
    """Invariant 7/8: the final 20% reserves synthesis; phase never goes back."""

    def test_reserve_moves_phase_to_synthesize(self):
        loop = _ProbeLoop(_SpyDispatcher(), max_steps=10)
        loop.state.step_count = 8  # exactly 80% of max_steps
        loop.evidence_log.record(tool="web_search", command_or_path="q",
                                 success=True, output_snippet="seed")
        forced = loop._maybe_force_partial_answer()
        self.assertTrue(forced)
        # PATCH-CORE-UNIFIED-R3: _commit_terminal_outcome advances phase to FINALIZE
        self.assertIn(loop._ctx.phase, ("SYNTHESIZE", "FINALIZE"))

    def test_progress_dispatch_cannot_move_phase_backwards(self):
        loop = _ProbeLoop(_SpyDispatcher())
        loop._ctx.phase = "SYNTHESIZE"
        loop._dispatch_and_record_evidence(
            ToolCall(tool="file_system", args={"action": "read", "path": "x.py"})
        )
        self.assertEqual(loop._ctx.phase, "SYNTHESIZE")  # monotone — never back to COLLECT


class TestStructuredPartialAnswer(unittest.TestCase):
    """Invariant 10: hard-limit fallback discards raw JSON for structured evidence."""

    def test_hard_limit_never_emits_raw_json(self):
        class _ForceFalseLoop(_ProbeLoop):
            def _maybe_force_partial_answer(self, force_cap=False):
                return False

        loop = _ForceFalseLoop(_SpyDispatcher())
        loop.evidence_log.record(tool="execute_shell", command_or_path="ls",
                                 success=True, output_snippet="a.py b.py c.py")
        loop._last_response = '{"tool": "execute_shell", "args": {"command": "ls"}}'
        loop._ctx.consecutive_no_progress = MAX_NO_PROGRESS_STEPS

        sig = loop._check_budget_and_guards()
        self.assertIs(sig, _LoopSignal.TERMINATE)
        # PATCH-CORE-UNIFIED-R3: check outcome from _commit_terminal_outcome, not emitted
        from core.turn_finalizer import TurnFinalizer
        _outcome = loop._turn_finalizer.outcome
        self.assertIsNotNone(_outcome)
        self.assertIn("Synthesized answer", loop._last_response)
        self.assertIn("a.py b.py c.py", loop._last_response)


class TestBroadProjectAnalysisCompletion(unittest.TestCase):
    """End-to-end: a broad productive run completes naturally (no early cap)."""

    def test_broad_analysis_completes_and_caps_stay_quiet(self):
        import json
        from unittest.mock import MagicMock
        from engine.loop import ExecutionLoop
        from engine.dispatcher import Dispatcher
        from engine.tool_registry import registry
        from tools.file_system import FileSystemTool
        from tools.todo import TodoWriteTool
        from core.todo import TodoManager

        class CountingDispatcher(Dispatcher):
            def __init__(self, state):
                super().__init__(state)
                self.real_calls = []

            def dispatch(self, tool_name, kwargs, timeout=30):
                self.real_calls.append((tool_name, dict(kwargs or {})))
                return super().dispatch(tool_name, kwargs, timeout=timeout)

        plan_args = {"action": "plan", "items": ["Survey the repository", "Read key source files"]}
        script = [
            {"tool": "todo_write", "args": plan_args},
            {"tool": "todo_write", "args": plan_args},  # identical — must be suppressed
            {"tool": "file_system", "args": {"action": "read", "path": "a.py"}},
            {"tool": "file_system", "args": {"action": "read", "path": "b.py"}},
            {"tool": "file_system", "args": {"action": "read", "path": "c.py"}},
            {"tool": "todo_write", "args": {"action": "update", "item_id": 1,
                                            "status": "done", "verification_note": "Files found (3 items)"}},
            {"tool": "todo_write", "args": {"action": "update", "item_id": 2,
                                            "status": "done", "verification_note": "Read a.py b.py c.py (3 files)"}},
            {"tool": "final_answer", "args": {"answer":
                "Architecture: a.py defines ALPHA, b.py defines BETA, c.py defines GAMMA."}},
        ]
        it = iter(script)

        state = RuntimeState(session_id="broad-analysis")
        dispatcher = CountingDispatcher(state)
        evidence = EvidenceLog()
        manager = TodoManager(evidence_log=evidence)

        with tempfile.TemporaryDirectory() as td:
            for name, body in (("a.py", "ALPHA = 1\n"), ("b.py", "BETA = 2\n"), ("c.py", "GAMMA = 3\n")):
                Path(td, name).write_text(body, encoding="utf-8")
            registry.register(FileSystemTool(workspace=td))
            registry.register("todo_write", TodoWriteTool(manager))

            loop = ExecutionLoop(
                state=state,
                llm_provider=MagicMock(side_effect=lambda *a, **k: json.dumps(next(it))),
                verifier_provider=MagicMock(return_value="APPROVED — independently verified."),
                dispatcher=dispatcher,
                evidence_log=evidence,
                todo_manager=manager,
                no_stream=True,
            )
            outcome = loop.run("Read and summarize these sample files")
            correctness = [Path(td, n).exists() for n in ("a.py", "b.py", "c.py")]
            self.assertTrue(all(correctness))

        # 1) identical TODO plan executed exactly ONCE: the repeat was
        #    suppressed before execution (cycle guard + todo suppression —
        #    both layers converge on "identical TODO never re-executes").
        plan_dispatches = [c for c in dispatcher.real_calls
                           if c[0] == "todo_write" and c[1].get("action") == "plan"]
        self.assertEqual(len(plan_dispatches), 1)
        read_dispatches = [c for c in dispatcher.real_calls if c[0] == "file_system"]
        self.assertEqual(len(read_dispatches), 3)

        # 2) counters: tool_call_count = real dispatched tool calls
        #    (1 plan + 3 reads + 2 updates = 6); total steps separate.
        self.assertEqual(loop._ctx.tool_call_count, 6)
        self.assertGreaterEqual(state.step_count, 7)

        # 3) productive run completed naturally — no no-progress/partial kill
        self.assertIsNotNone(outcome)
        self.assertEqual(state.status, "COMPLETED")
        self.assertEqual(loop._ctx.phase, "FINALIZE")
        self.assertIn("ALPHA", loop._last_response)


if __name__ == "__main__":
    unittest.main()
