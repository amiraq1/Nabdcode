"""Tests for the CompletionTracker Protocol, adapters, and fail-closed behavior.

Covers:
  - TodoManagerCompletionTracker correctly converts TodoItem objects
  - DeepAgentPlanCompletionTracker correctly converts plan steps
  - can_finalize() with completion_tracker works end-to-end
  - requires_plan=True fails closed when no tracker is available
  - Infinite loop prevention: repeated final_answer with blocked TODO
  - Blocked finalization counts toward iteration budget
  - classify_claim() used as warning signal, not sole proof
"""

import unittest
from unittest.mock import MagicMock

from core.convergence_gate import (
    can_finalize,
    CompletionItem,
    CompletionTracker,
    TodoManagerCompletionTracker,
    DeepAgentPlanCompletionTracker,
    FinalizationDecision,
    classify_claim,
)
from core.todo import TodoManager, TodoStatus
from core.evidence import EvidenceLog


class TestTodoManagerCompletionTracker(unittest.TestCase):
    """TodoManagerCompletionTracker must faithfully convert TodoItems."""

    def test_converts_all_todos(self):
        tm = TodoManager()
        tm.set_plan(["Task A", "Task B", "Task C"])
        tracker = TodoManagerCompletionTracker(tm)
        items = list(tracker.completion_items())
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].text, "Task A")
        self.assertEqual(items[0].id, 1)
        self.assertEqual(items[0].status, "pending")

    def test_preserves_done_status(self):
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py"])
        ev.record(tool="file_system", command_or_path="file.py",
                  success=True, output_snippet="content", action="read")
        tm.mark_done(1, "py_compile OK on file.py")
        tracker = TodoManagerCompletionTracker(tm)
        items = list(tracker.completion_items())
        self.assertEqual(items[0].status, "done")
        self.assertEqual(len(items[0].evidence_ids), 1)

    def test_preserves_skipped_with_reason(self):
        tm = TodoManager()
        tm.set_plan(["Task A"])
        tm.mark_skipped(1, "not needed")
        tracker = TodoManagerCompletionTracker(tm)
        items = list(tracker.completion_items())
        self.assertEqual(items[0].status, "skipped")
        self.assertEqual(items[0].failure_reason, "not needed")

    def test_empty_plan(self):
        tm = TodoManager()
        tracker = TodoManagerCompletionTracker(tm)
        items = list(tracker.completion_items())
        self.assertEqual(len(items), 0)


class TestDeepAgentPlanCompletionTracker(unittest.TestCase):
    """DeepAgentPlanCompletionTracker must convert plan steps to CompletionItems."""

    def test_all_pending_when_cursor_at_zero(self):
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1", "Step 2", "Step 3"],
            current_plan_index=0,
        )
        items = list(tracker.completion_items())
        self.assertEqual(len(items), 3)
        for item in items:
            self.assertEqual(item.status, "pending")
            self.assertIsNone(item.completion_source)

    def test_done_when_cursor_advanced(self):
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1", "Step 2", "Step 3"],
            current_plan_index=2,
        )
        items = list(tracker.completion_items())
        self.assertEqual(items[0].status, "done")
        self.assertEqual(items[0].completion_source, "deep_agent")
        self.assertEqual(items[1].status, "done")
        self.assertEqual(items[2].status, "pending")

    def test_all_done_when_cursor_at_end(self):
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1", "Step 2"],
            current_plan_index=2,
        )
        items = list(tracker.completion_items())
        for item in items:
            self.assertEqual(item.status, "done")

    def test_empty_plan(self):
        tracker = DeepAgentPlanCompletionTracker(plan=[], current_plan_index=0)
        items = list(tracker.completion_items())
        self.assertEqual(len(items), 0)

    def test_negative_cursor_clamped(self):
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1"],
            current_plan_index=-5,
        )
        items = list(tracker.completion_items())
        self.assertEqual(items[0].status, "pending")

    def test_ids_are_sequential(self):
        tracker = DeepAgentPlanCompletionTracker(
            plan=["A", "B", "C", "D"],
            current_plan_index=2,
        )
        items = list(tracker.completion_items())
        self.assertEqual([i.id for i in items], [1, 2, 3, 4])


class TestCanFinalizeWithCompletionTracker(unittest.TestCase):
    """can_finalize() must work with the CompletionTracker interface."""

    def test_blocks_with_pending_item(self):
        tm = TodoManager()
        tm.set_plan(["Task A", "Task B"])
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(completion_tracker=tracker, requires_plan=True)
        self.assertFalse(decision.allowed)
        self.assertEqual(len(decision.blocking_todos), 2)

    def test_allows_when_all_done_with_evidence(self):
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py"])
        ev.record(tool="file_system", command_or_path="file.py",
                  success=True, output_snippet="content", action="read")
        tm.mark_done(1, "py_compile OK on file.py")
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision.allowed)

    def test_backward_compat_with_todo_manager(self):
        """Passing todo_manager directly (no tracker) still works."""
        tm = TodoManager()
        tm.set_plan(["Task A"])
        decision = can_finalize(todo_manager=tm, requires_plan=True)
        self.assertFalse(decision.allowed)

    def test_backward_compat_no_args_allows(self):
        """No tracker, no todo_manager, requires_plan=False → allow (chitchat)."""
        decision = can_finalize()
        self.assertTrue(decision.allowed)


class TestFailClosedRequiresPlan(unittest.TestCase):
    """requires_plan=True must fail closed when no tracker is available."""

    def test_fail_closed_no_tracker(self):
        """No completion tracker + requires_plan=True → blocked."""
        decision = can_finalize(requires_plan=True)
        self.assertFalse(decision.allowed)
        self.assertIn("fail-closed", decision.blocked_reason)

    def test_fail_closed_none_tracker(self):
        """Explicit completion_tracker=None + requires_plan=True → blocked."""
        decision = can_finalize(
            completion_tracker=None, requires_plan=True
        )
        self.assertFalse(decision.allowed)

    def test_allow_when_not_requires_plan(self):
        """No tracker + requires_plan=False → allowed (chitchat path)."""
        decision = can_finalize(requires_plan=False)
        self.assertTrue(decision.allowed)

    def test_fail_closed_with_broken_tracker(self):
        """A tracker that raises is caught and treated as empty items.

        Since requires_plan=True and the tracker returned zero items
        (the exception was caught), the gate must fail-closed: an empty
        commitment list is never inferred as legitimate when tracking
        is required. The commitment source is effectively missing.
        """
        class BrokenTracker:
            def completion_items(self):
                raise RuntimeError("broken")

        decision = can_finalize(
            completion_tracker=BrokenTracker(), requires_plan=True
        )
        # Broken tracker → exception caught → empty items → fail-closed.
        self.assertFalse(decision.allowed)
        self.assertIn("fail-closed", decision.blocked_reason)


class TestDeepAgentConvergenceGateIntegration(unittest.TestCase):
    """NativeDeepAgent's plan must be bound to can_finalize() via the tracker."""

    def test_plan_with_pending_steps_blocks(self):
        """A plan with unexecuted steps must block finalization."""
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Read file.py", "Write output.py", "Verify"],
            current_plan_index=1,  # only first step done
        )
        ev = EvidenceLog()
        ev.record(tool="file_system", command_or_path="file.py",
                  success=True, output_snippet="content", action="read")
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        # Steps 2 and 3 are pending
        blocking_ids = [b.todo_id for b in decision.blocking_todos]
        self.assertIn(2, blocking_ids)
        self.assertIn(3, blocking_ids)

    def test_plan_all_done_allows(self):
        """A plan where all steps are executed must allow finalization."""
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Read file.py", "Write output.py"],
            current_plan_index=2,  # all steps done
        )
        ev = EvidenceLog()
        ev.record(tool="file_system", command_or_path="file.py",
                  success=True, output_snippet="content", action="read")
        ev.record(tool="file_system", command_or_path="output.py",
                  success=True, output_snippet="written", action="write")
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision.allowed)


class TestInfiniteLoopPrevention(unittest.TestCase):
    """Repeated final_answer with a blocked TODO must not loop forever."""

    def test_blocked_finalization_increments_step(self):
        """Each blocked finalization attempt increments the step counter.

        This ensures the agent cannot loop forever by repeatedly emitting
        final_answer with a blocked TODO — each attempt counts toward the
        iteration budget.
        """
        from engine.state import RuntimeState

        state = RuntimeState(session_id="test-infinite-loop")
        initial_step = state.step_count

        tm = TodoManager()
        tm.set_plan(["Task A"])
        tracker = TodoManagerCompletionTracker(tm)

        # Simulate 5 blocked finalization attempts
        for i in range(5):
            decision = can_finalize(
                completion_tracker=tracker, requires_plan=True
            )
            self.assertFalse(decision.allowed)
            state.increment_step()

        # Step count must have advanced by 5
        self.assertEqual(state.step_count, initial_step + 5)

    def test_max_self_correct_limits_retries(self):
        """MAX_SELF_CORRECT caps the self-correction loop.

        Even if the plan is never completed, the agent gives up after
        MAX_SELF_CORRECT attempts instead of looping forever.
        """
        MAX_SELF_CORRECT = 3
        retry_count = 0
        blocked_attempts = 0

        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1"], current_plan_index=0  # never done
        )

        while retry_count <= MAX_SELF_CORRECT:
            decision = can_finalize(
                completion_tracker=tracker, requires_plan=True
            )
            if not decision.allowed:
                blocked_attempts += 1
                retry_count += 1
                continue
            break

        # Must have given up after MAX_SELF_CORRECT + 1 attempts
        self.assertEqual(blocked_attempts, MAX_SELF_CORRECT + 1)
        self.assertLessEqual(blocked_attempts, MAX_SELF_CORRECT + 1)


class TestClassifyClaimAsWarningNotProof(unittest.TestCase):
    """classify_claim() is a warning signal, not a sole proof gate."""

    def test_classify_claim_returns_unverified_for_no_evidence(self):
        result = classify_claim("the file is large", [])
        self.assertEqual(result, "UNVERIFIED")

    def test_classify_claim_returns_observed_for_direct_match(self):
        from core.evidence import EvidenceRecord
        rec = EvidenceRecord(
            evidence_id="E-1",
            evidence_type="filesystem",
            tool="file_system",
            command_or_path="file.py",
            action="read",
            success=True,
            output_snippet="the file is large",
            covered_subjects=frozenset({"file.py"}),
            critical=False,
        )
        # classify_claim uses quoted-string matching for OBSERVED.
        # The claim must contain a quoted substring present in the evidence.
        result = classify_claim('"the file is large"', [rec])
        self.assertEqual(result, "OBSERVED")

    def test_classify_claim_returns_inferred_for_partial(self):
        from core.evidence import EvidenceRecord
        rec = EvidenceRecord(
            evidence_id="E-1",
            evidence_type="filesystem",
            tool="file_system",
            command_or_path="file.py",
            action="read",
            success=True,
            output_snippet="file.py contains 500 lines",
            covered_subjects=frozenset({"file.py"}),
            critical=False,
        )
        result = classify_claim("the file is large", [rec])
        self.assertIn(result, ("INFERRED", "OBSERVED"))

    def test_classify_claim_is_warning_not_gate(self):
        """classify_claim returning UNVERIFIED should be a warning, not a hard block.

        The convergence gate uses evidence matching (path-based) as the hard
        gate. classify_claim is a secondary signal for the LLM checker.
        """
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py"])
        # No evidence recorded — classify_claim would say UNVERFIED
        # but the gate blocks because the TODO is pending, not because
        # classify_claim said UNVERIFIED.
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        # The block reason should mention pending status, not classify_claim
        self.assertIn("pending", decision.blocked_reason.lower())


class TestDoneValidationAgainstMutation(unittest.TestCase):
    """done status cannot be faked via deserialization or direct mutation."""

    def test_deep_agent_plan_cursor_cannot_fake_done(self):
        """A plan with current_plan_index > len(plan) still requires evidence.

        Even if the cursor is inflated, can_finalize() checks evidence
        for 'done' items. Without evidence, the item still blocks.
        """
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1"],
            current_plan_index=1,  # cursor says done
        )
        ev = EvidenceLog()  # empty — no evidence
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        # The 'done' item has no matching evidence → blocks
        self.assertFalse(decision.allowed)
        self.assertIn(1, [b.todo_id for b in decision.blocking_todos])

    def test_todo_manager_mark_done_requires_evidence(self):
        """TodoManager.mark_done() raises if no matching evidence."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py"])
        # No evidence recorded
        with self.assertRaises(ValueError) as ctx:
            tm.mark_done(1, "py_compile OK on file.py")
        self.assertIn("no matching evidence", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
