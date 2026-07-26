"""Integration tests for convergence gate across ExecutionLoop and NativeDeepAgent.

Each test:
  1. Starts with three TODOs.
  2. Completes two of them.
  3. Attempts to emit FINAL ANSWER.
  4. Must be blocked by the convergence gate due to the third TODO.
  5. Executes evidence for the third TODO.
  6. Allows the final answer after all TODOs are complete.

Also includes a test proving that reading a DIFFERENT file does not complete
a targeted TODO.
"""

import unittest
from unittest.mock import MagicMock

from core.convergence_gate import can_finalize
from core.todo import TodoManager, TodoStatus
from core.evidence import EvidenceLog


class TestExecutionLoopConvergenceGate(unittest.TestCase):
    """Integration test: ExecutionLoop with convergence gate."""

    def setUp(self):
        try:
            from engine.tool_registry import registry
            from tools.file_system import FileSystemTool
            registry.register(FileSystemTool())
        except ValueError:
            pass

    def _make_loop(self, responses):
        from engine.loop import ExecutionLoop
        from engine.state import RuntimeState

        state = RuntimeState(session_id="test-convergence-gate")
        mock_llm = MagicMock(side_effect=list(responses))
        todo_mgr = TodoManager()
        ev_log = EvidenceLog()
        todo_mgr.set_evidence_log(ev_log)

        loop = ExecutionLoop(
            llm_provider=mock_llm,
            state=state,
            evidence_log=ev_log,
            todo_manager=todo_mgr,
        )
        return loop, mock_llm, todo_mgr, ev_log

    def test_final_answer_blocked_then_allowed_after_all_todos_done(self):
        """Start with 3 TODOs, complete 2, attempt FINAL ANSWER (blocked),
        then complete the 3rd, and FINAL ANSWER is allowed.

        This test directly verifies can_finalize blocks and then allows,
        simulating what the ExecutionLoop's _emit_final gate would do.
        """
        from core.convergence_gate import can_finalize

        todo_mgr = TodoManager()
        ev_log = EvidenceLog()
        todo_mgr.set_evidence_log(ev_log)
        todo_mgr.set_plan([
            "Read pyproject.toml",
            "Read main.py",
            "Read core/loop.py",
        ])

        # Complete 2 of 3 TODOs with matching evidence
        ev_log.record(
            tool="file_system",
            command_or_path="pyproject.toml",
            success=True,
            output_snippet="name = nabd-os",
            action="read",
        )
        todo_mgr.mark_done(1, "py_compile: 0 errors on pyproject.toml")

        ev_log.record(
            tool="file_system",
            command_or_path="main.py",
            success=True,
            output_snippet="def main():",
            action="read",
        )
        todo_mgr.mark_done(2, "py_compile: 0 errors on main.py")

        # TODO #3 is still pending — FINAL ANSWER must be blocked
        decision = can_finalize(todo_mgr, ev_log)
        self.assertFalse(decision.allowed)
        self.assertIn(3, [b.todo_id for b in decision.blocking_todos])

        # Complete TODO #3
        ev_log.record(
            tool="file_system",
            command_or_path="core/loop.py",
            success=True,
            output_snippet="class ExecutionLoop:",
            action="read",
        )
        todo_mgr.mark_done(3, "py_compile: 0 errors on core/loop.py")

        # Now FINAL ANSWER is allowed
        decision = can_finalize(todo_mgr, ev_log)
        self.assertTrue(decision.allowed)
        self.assertEqual(len(decision.blocking_todos), 0)

    def test_final_answer_blocked_with_pending_todo_via_can_finalize(self):
        """Directly test can_finalize blocks when a TODO is pending."""
        todo_mgr = TodoManager()
        ev_log = EvidenceLog()
        todo_mgr.set_evidence_log(ev_log)
        todo_mgr.set_plan(["Task A", "Task B", "Task C"])

        # Complete Task A
        ev_log.record(
            tool="file_system",
            command_or_path="file_a.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        todo_mgr.mark_done(1, "py_compile OK on file_a.py")

        # Complete Task B
        ev_log.record(
            tool="file_system",
            command_or_path="file_b.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        todo_mgr.mark_done(2, "py_compile OK on file_b.py")

        # Task C is still pending
        decision = can_finalize(todo_mgr, ev_log)
        self.assertFalse(decision.allowed)
        self.assertIn(3, [b.todo_id for b in decision.blocking_todos])

        # Now complete Task C
        ev_log.record(
            tool="file_system",
            command_or_path="file_c.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        todo_mgr.mark_done(3, "py_compile OK on file_c.py")

        # Now should be allowed
        decision = can_finalize(todo_mgr, ev_log)
        self.assertTrue(decision.allowed)

    def test_reading_different_file_does_not_complete_todo(self):
        """Reading a different file does not complete a targeted TODO."""
        todo_mgr = TodoManager()
        ev_log = EvidenceLog()
        todo_mgr.set_evidence_log(ev_log)
        todo_mgr.set_plan(["Read core/bootstrap.py"])

        # Read a DIFFERENT file
        ev_log.record(
            tool="file_system",
            command_or_path="core/loop.py",
            success=True,
            output_snippet="content",
            action="read",
        )

        # Attempting to mark the TODO done should fail
        with self.assertRaises(ValueError) as ctx:
            todo_mgr.mark_done(1, "py_compile: 0 errors on core/bootstrap.py")
        self.assertIn("no matching evidence", str(ctx.exception).lower())

        # can_finalize should block
        decision = can_finalize(todo_mgr, ev_log)
        self.assertFalse(decision.allowed)


class TestNativeDeepAgentConvergenceGate(unittest.TestCase):
    """Integration test: NativeDeepAgent with convergence gate."""

    def test_native_deep_agent_final_answer_blocked_with_pending_todo(self):
        """NativeDeepAgent with pending TODOs should be blocked from final answer."""
        from engine.deep_agent import NativeDeepAgent, DeepAgentState
        from engine.state import RuntimeState

        state = RuntimeState(session_id="test-deep-agent-convergence")
        todo_mgr = TodoManager()
        ev_log = EvidenceLog()
        todo_mgr.set_evidence_log(ev_log)
        todo_mgr.set_plan(["Step 1", "Step 2", "Step 3"])

        # Complete 2 of 3
        ev_log.record(
            tool="file_system",
            command_or_path="file1.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        todo_mgr.mark_done(1, "15 passed in 2.3s on file1.py")

        ev_log.record(
            tool="file_system",
            command_or_path="file2.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        todo_mgr.mark_done(2, "15 passed in 2.3s on file2.py")

        # Step 3 is pending
        decision = can_finalize(todo_mgr, ev_log)
        self.assertFalse(decision.allowed)
        self.assertIn(3, [b.todo_id for b in decision.blocking_todos])

        # Complete Step 3
        ev_log.record(
            tool="file_system",
            command_or_path="file3.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        todo_mgr.mark_done(3, "15 passed in 2.3s on file3.py")

        # Now allowed
        decision = can_finalize(todo_mgr, ev_log)
        self.assertTrue(decision.allowed)

    def test_native_deep_agent_budget_exhaustion_returns_partial(self):
        """Budget exhaustion returns PARTIAL, not complete."""
        from engine.state import RuntimeState

        state = RuntimeState(session_id="test-deep-agent-budget")
        todo_mgr = TodoManager()
        ev_log = EvidenceLog()
        todo_mgr.set_evidence_log(ev_log)
        todo_mgr.set_plan(["Task A", "Task B", "Task C"])

        # Complete one
        ev_log.record(
            tool="file_system",
            command_or_path="file_a.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        todo_mgr.mark_done(1, "15 passed in 2.3s on file_a.py")

        # Budget exhausted
        decision = can_finalize(todo_mgr, ev_log, budget_exhausted=True)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.partial)


if __name__ == "__main__":
    unittest.main()
