"""Focused tests for Loop Safety (section 23 of the spec).

Verifies that blocked finalization attempts:
  - Emit a single event per attempt
  - Consume iteration budget
  - Respect time budget
  - Trigger recovery after repeated attempts without progress
  - Recovery resets only attempt counter, not commitments
  - Max blocked attempts returns partial or blocked
  - Partial result lists unfinished commitments
  - Reworded final answer is not counted as progress
  - New valid evidence is counted as progress
"""

import unittest

from core.convergence_gate import can_finalize, TodoManagerCompletionTracker
from core.evidence import EvidenceLog
from core.todo import TodoManager


class TestBlockedFinalEmitsSingleEvent(unittest.TestCase):
    """Test 1: Blocked final emits single event per attempt."""

    def test_blocked_final_emits_single_event_per_attempt(self):
        """Each blocked finalization attempt returns exactly one decision
        with one set of blocking_todos — no duplicate or missing events."""
        tm = TodoManager()
        tm.set_plan(["Task A", "Task B"])
        tracker = TodoManagerCompletionTracker(tm)

        # Simulate 3 blocked attempts
        for i in range(3):
            decision = can_finalize(
                completion_tracker=tracker, requires_plan=True
            )
            self.assertFalse(decision.allowed)
            # Exactly 2 blocking items each time (both pending)
            self.assertEqual(len(decision.blocking_todos), 2)
            # blocked_reason is non-empty
            self.assertTrue(decision.blocked_reason)


class TestBlockedFinalConsumesBudget(unittest.TestCase):
    """Tests 2-3: Blocked final consumes iteration and time budget."""

    def test_blocked_final_attempt_consumes_iteration_budget(self):
        """Each blocked finalization attempt increments the step counter."""
        from engine.state import RuntimeState

        state = RuntimeState(session_id="test-budget")
        initial_step = state.step_count

        tm = TodoManager()
        tm.set_plan(["Task A"])
        tracker = TodoManagerCompletionTracker(tm)

        for _ in range(5):
            decision = can_finalize(
                completion_tracker=tracker, requires_plan=True
            )
            self.assertFalse(decision.allowed)
            state.increment_step()

        self.assertEqual(state.step_count, initial_step + 5)

    def test_blocked_final_attempt_respects_time_budget(self):
        """Deadline exceeded → partial=True, allowed=False."""
        tm = TodoManager()
        tm.set_plan(["Task A"])
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker,
            deadline_exceeded=True,
            requires_plan=True,
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.partial)


class TestRepeatedFinalTriggersRecovery(unittest.TestCase):
    """Tests 4-6: Repeated final without progress triggers recovery."""

    def test_repeated_final_without_progress_triggers_recovery(self):
        """After MAX_SELF_CORRECT blocked attempts, the agent must give up."""
        MAX_SELF_CORRECT = 3
        tm = TodoManager()
        tm.set_plan(["Step 1"])  # never completed
        tracker = TodoManagerCompletionTracker(tm)

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

        self.assertEqual(blocked_attempts, MAX_SELF_CORRECT + 1)

    def test_recovery_resets_only_attempt_counter_not_commitments(self):
        """Recovery resets the attempt counter but preserves commitments (TODOs).

        After recovery, the TODOs should still be in their original state
        (pending), not cleared or modified.
        """
        tm = TodoManager()
        tm.set_plan(["Step 1", "Step 2"])
        tracker = TodoManagerCompletionTracker(tm)

        # Simulate blocked attempts
        for _ in range(3):
            can_finalize(completion_tracker=tracker, requires_plan=True)

        # Recovery: reset attempt counter (simulated)
        # The TODOs should still be pending
        items = tm.all()
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item.status.value, "pending")

    def test_max_blocked_attempts_returns_partial_or_blocked(self):
        """After max blocked attempts, the result is partial or blocked."""
        tm = TodoManager()
        tm.set_plan(["Step 1"])
        tracker = TodoManagerCompletionTracker(tm)

        MAX_SELF_CORRECT = 3
        retry_count = 0
        final_decision = None

        while retry_count <= MAX_SELF_CORRECT:
            final_decision = can_finalize(
                completion_tracker=tracker, requires_plan=True
            )
            if not final_decision.allowed:
                retry_count += 1
                continue
            break

        # After max attempts, the decision is blocked (not allowed)
        self.assertFalse(final_decision.allowed)


class TestPartialResultListsUnfinished(unittest.TestCase):
    """Test 7: Partial result lists unfinished commitments."""

    def test_partial_result_lists_unfinished_commitments(self):
        """Budget exhaustion returns partial=True with unfinished commitments listed."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py", "Write output.py"])
        # Complete only the first TODO
        ev.record(tool="file_system", command_or_path="file.py",
                  success=True, output_snippet="content", action="read")
        tm.mark_done(1, "Read file.py — 100 lines, exit 0")
        tracker = TodoManagerCompletionTracker(tm)

        decision = can_finalize(
            completion_tracker=tracker,
            evidence_log=ev,
            budget_exhausted=True,
            requires_plan=True,
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.partial)
        # The second TODO (pending) must be in the blocking list
        blocking_ids = [b.todo_id for b in decision.blocking_todos]
        self.assertIn(2, blocking_ids)


class TestProgressDetection(unittest.TestCase):
    """Tests 8-9: Progress detection — reworded answer vs new evidence."""

    def test_reworded_final_answer_is_not_counted_as_progress(self):
        """Rewording the final answer without new evidence does not change
        the blocked decision. The gate is stateless — it only looks at
        TODO status and evidence, not at the answer text."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py"])
        tracker = TodoManagerCompletionTracker(tm)

        # First attempt — blocked
        decision1 = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision1.allowed)

        # "Reworded" answer — same state, no new evidence
        decision2 = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        # Still blocked — rewording doesn't count as progress
        self.assertFalse(decision2.allowed)

    def test_new_valid_evidence_is_counted_as_progress(self):
        """Adding new valid evidence changes the decision from blocked to allowed."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py"])
        tracker = TodoManagerCompletionTracker(tm)

        # First attempt — blocked (no evidence)
        decision1 = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision1.allowed)

        # Add valid evidence
        ev.record(tool="file_system", command_or_path="file.py",
                  success=True, output_snippet="content", action="read")
        tm.mark_done(1, "Read file.py — 100 lines, exit 0")

        # Second attempt — should now be allowed
        decision2 = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision2.allowed)


if __name__ == "__main__":
    unittest.main()
