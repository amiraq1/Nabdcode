"""Focused tests for NativeDeepAgent convergence gate integration.

Covers the 14 required scenarios from section 21 of the closure-blocker spec:
  1.  blocks_final_with_pending_plan_item
  2.  blocks_final_with_in_progress_plan_item
  3.  allows_final_when_required_plan_is_complete
  4.  blocks_when_completion_tracker_missing
  5.  done_item_requires_policy_evidence
  6.  budget_exhaustion_returns_partial
  7.  timeout_returns_partial_or_blocked
  8.  repeated_blocked_final_does_not_loop_forever
  9.  blocked_item_requires_reason
  10. skipped_item_requires_reason
  11. required_item_cannot_be_silently_skipped
  12. both_engines_use_same_finalization_policy
  13. empty_plan_allowed_only_when_tracking_not_required
  14. missing_tracker_fails_closed_when_tracking_required
"""

import unittest

from core.convergence_gate import (
    can_finalize,
    DeepAgentPlanCompletionTracker,
    TodoManagerCompletionTracker,
    FinalizationDecision,
)
from core.evidence import EvidenceLog
from core.todo import TodoManager, TodoStatus


class TestNativeDeepAgentBlocksFinal(unittest.TestCase):
    """Tests 1-3: NativeDeepAgent plan items block/allow finalization."""

    def test_native_deep_agent_blocks_final_with_pending_plan_item(self):
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
        blocking_ids = [b.todo_id for b in decision.blocking_todos]
        self.assertIn(2, blocking_ids)
        self.assertIn(3, blocking_ids)

    def test_native_deep_agent_blocks_final_with_in_progress_plan_item(self):
        """A plan with the current step in_progress (cursor not advanced) blocks."""
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step A", "Step B"],
            current_plan_index=0,  # nothing done yet
        )
        decision = can_finalize(
            completion_tracker=tracker, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        # Both items are pending
        self.assertEqual(len(decision.blocking_todos), 2)

    def test_native_deep_agent_allows_final_when_required_plan_is_complete(self):
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


class TestNativeDeepAgentTrackerMissing(unittest.TestCase):
    """Tests 4, 13, 14: Tracker availability and fail-closed behavior."""

    def test_native_deep_agent_blocks_when_completion_tracker_missing(self):
        """No tracker + requires_plan=True → blocked (fail-closed)."""
        decision = can_finalize(requires_plan=True)
        self.assertFalse(decision.allowed)
        self.assertIn("fail-closed", decision.blocked_reason)

    def test_empty_plan_allowed_only_when_tracking_not_required(self):
        """Empty plan + requires_plan=False → allowed (chitchat)."""
        tracker = DeepAgentPlanCompletionTracker(plan=[], current_plan_index=0)
        decision = can_finalize(
            completion_tracker=tracker, requires_plan=False
        )
        self.assertTrue(decision.allowed)

    def test_missing_tracker_fails_closed_when_tracking_required(self):
        """Missing tracker + requires_plan=True → fail-closed."""
        decision = can_finalize(
            completion_tracker=None, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        self.assertIn("fail-closed", decision.blocked_reason)


class TestNativeDeepAgentEvidenceRequirements(unittest.TestCase):
    """Tests 5, 9, 10, 11: Evidence and reason requirements."""

    def test_native_deep_agent_done_item_requires_policy_evidence(self):
        """A 'done' item without matching evidence must block."""
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Read file.py"],
            current_plan_index=1,  # cursor says done
        )
        ev = EvidenceLog()  # empty — no evidence
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        self.assertIn(1, [b.todo_id for b in decision.blocking_todos])

    def test_native_deep_agent_blocked_item_requires_reason(self):
        """A 'blocked' item without a reason must block finalization."""
        tm = TodoManager()
        tm.set_plan(["Task A"])
        # Directly set status to BLOCKED without a reason (bypass mark_blocked
        # which enforces non-empty reason at the TodoManager level).
        item = tm._get(1)
        item.status = TodoStatus.BLOCKED
        item.failure_reason = None
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        self.assertIn(1, [b.todo_id for b in decision.blocking_todos])

    def test_native_deep_agent_skipped_item_requires_reason(self):
        """A 'skipped' item without a reason must block finalization."""
        tm = TodoManager()
        tm.set_plan(["Task A"])
        # Directly set status to SKIPPED without a reason.
        item = tm._get(1)
        item.status = TodoStatus.SKIPPED
        item.failure_reason = None
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        self.assertIn(1, [b.todo_id for b in decision.blocking_todos])

    def test_native_deep_agent_required_item_cannot_be_silently_skipped(self):
        """Skipping a required item without a reason must block."""
        tm = TodoManager()
        tm.set_plan(["Required task"])
        # mark_skipped with empty reason raises ValueError (cannot skip silently)
        with self.assertRaises(ValueError):
            tm.mark_skipped(1, "")


class TestNativeDeepAgentBudgetAndTimeout(unittest.TestCase):
    """Tests 6, 7, 8: Budget exhaustion, timeout, loop safety."""

    def test_native_deep_agent_budget_exhaustion_returns_partial(self):
        """Budget exhaustion → partial=True, allowed=False."""
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1", "Step 2"],
            current_plan_index=1,  # step 2 pending
        )
        decision = can_finalize(
            completion_tracker=tracker,
            budget_exhausted=True,
            requires_plan=True,
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.partial)

    def test_native_deep_agent_timeout_returns_partial_or_blocked(self):
        """Timeout → partial=True, allowed=False."""
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1"],
            current_plan_index=0,  # pending
        )
        decision = can_finalize(
            completion_tracker=tracker,
            deadline_exceeded=True,
            requires_plan=True,
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.partial)

    def test_native_deep_agent_repeated_blocked_final_does_not_loop_forever(self):
        """Repeated blocked finalization attempts must not loop forever.

        Each attempt returns the same blocked decision; the caller
        (NativeDeepAgent.run) caps retries at MAX_SELF_CORRECT.
        """
        tracker = DeepAgentPlanCompletionTracker(
            plan=["Step 1"],
            current_plan_index=0,  # never done
        )
        MAX_SELF_CORRECT = 3
        retry_count = 0
        blocked_attempts = 0

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


class TestBothEnginesSamePolicy(unittest.TestCase):
    """Test 12: Both engines use the same finalization policy."""

    def test_both_engines_use_same_finalization_policy(self):
        """ExecutionLoop (TodoManager) and NativeDeepAgent (plan) must
        produce the same decision for equivalent incomplete state."""
        # ExecutionLoop path: TodoManager with a pending item
        tm = TodoManager()
        tm.set_plan(["Read file.py"])
        loop_tracker = TodoManagerCompletionTracker(tm)
        loop_decision = can_finalize(
            completion_tracker=loop_tracker, requires_plan=True
        )

        # NativeDeepAgent path: plan with a pending step
        deep_tracker = DeepAgentPlanCompletionTracker(
            plan=["Read file.py"],
            current_plan_index=0,
        )
        deep_decision = can_finalize(
            completion_tracker=deep_tracker, requires_plan=True
        )

        # Both must block with the same allowed=False
        self.assertFalse(loop_decision.allowed)
        self.assertFalse(deep_decision.allowed)
        # Both must report 1 blocking item
        self.assertEqual(len(loop_decision.blocking_todos), 1)
        self.assertEqual(len(deep_decision.blocking_todos), 1)


if __name__ == "__main__":
    unittest.main()
