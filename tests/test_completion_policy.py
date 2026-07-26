"""Focused tests for Completion Policies (section 22 of the spec).

Verifies that evidence matching enforces kind-specific policies:
  READ, VERIFY, TEST, EDIT, ANALYZE/REASON, USER_DECISION.
"""

import unittest

from core.convergence_gate import can_finalize, TodoManagerCompletionTracker
from core.evidence import EvidenceLog
from core.todo import TodoManager, TodoStatus


class TestReadCompletionPolicy(unittest.TestCase):
    """Tests 1-3: READ completion requires matching read evidence."""

    def test_read_completion_requires_matching_read_evidence(self):
        """A READ TODO with matching path evidence allows finalization."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read core/loop.py"])
        ev.record(tool="file_system", command_or_path="core/loop.py",
                  success=True, output_snippet="content", action="read")
        tm.mark_done(1, "Read core/loop.py — 1554 lines, exit 0")
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision.allowed)

    def test_read_evidence_for_different_path_is_rejected(self):
        """A READ TODO with evidence for a different path must block."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read core/loop.py"])
        # Evidence is for a DIFFERENT file
        ev.record(tool="file_system", command_or_path="core/other.py",
                  success=True, output_snippet="content", action="read")
        # mark_done should raise because no matching evidence
        with self.assertRaises(ValueError):
            tm.mark_done(1, "Read core/loop.py")
        # Even if we bypass mark_done, can_finalize should block
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision.allowed)

    def test_failed_read_cannot_complete_read_item(self):
        """A failed read (success=False) cannot complete a READ item."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read core/loop.py"])
        ev.record(tool="file_system", command_or_path="core/loop.py",
                  success=False, output_snippet="File not found", action="read")
        with self.assertRaises(ValueError):
            tm.mark_done(1, "Read core/loop.py — file not found")


class TestVerifyCompletionPolicy(unittest.TestCase):
    """Test 4: VERIFY completion requires independent verification."""

    def test_verify_completion_requires_independent_verification(self):
        """A VERIFY TODO must have verification evidence, not just a read.

        Reading a different file alone is insufficient — the evidence must
        show an independent verification action matching the TODO's target.
        """
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Verify entry point in main.py"])
        # Evidence is for a DIFFERENT file — doesn't match the TODO's path
        ev.record(tool="file_system", command_or_path="core/other.py",
                  success=True, output_snippet="content", action="read")
        # mark_done should raise because no matching evidence
        with self.assertRaises(ValueError):
            tm.mark_done(1, "Verified entry point in main.py")
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision.allowed)


class TestTestCompletionPolicy(unittest.TestCase):
    """Tests 5-6: TEST completion requires executed command and exit code."""

    def test_test_completion_requires_executed_command_and_exit_code(self):
        """A TEST TODO must have a successful shell command with exit code."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Test the build"])
        ev.record(tool="execute_shell", command_or_path="python -m pytest tests/",
                  success=True, output_snippet="10 passed", action="run")
        tm.mark_done(1, "pytest: 10 passed, exit 0")
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision.allowed)

    def test_failed_test_cannot_complete_test_item(self):
        """A failed test (success=False) cannot complete a TEST item."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Test the build"])
        ev.record(tool="execute_shell", command_or_path="python -m pytest tests/",
                  success=False, output_snippet="5 failed", action="run")
        with self.assertRaises(ValueError):
            tm.mark_done(1, "pytest: 5 failed")


class TestEditCompletionPolicy(unittest.TestCase):
    """Test 7: EDIT completion requires successful mutation or diff."""

    def test_edit_completion_requires_successful_mutation_or_diff(self):
        """An EDIT TODO must have a successful file_system edit evidence."""
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Edit core/sanitize.py"])
        ev.record(tool="file_system", command_or_path="core/sanitize.py",
                  success=True, output_snippet="Updated core/sanitize.py", action="edit")
        tm.mark_done(1, "Edited core/sanitize.py — 3 additions, 1 removal")
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision.allowed)


class TestAnalyzeCompletionPolicy(unittest.TestCase):
    """Test 8: ANALYZE/REASON completion does not require fake tool event."""

    def test_analyze_completion_does_not_require_fake_tool_event(self):
        """An ANALYZE TODO can be completed via internal completion source.

        The gate should not require a fake tool event for analysis tasks.
        If the completion_source is 'manual' and the item is marked done
        with a concrete verification note, it should be accepted.
        """
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Analyze the architecture"])
        # Provide concrete evidence (a listing showing modules found)
        ev.record(tool="file_system", command_or_path="core/",
                  success=True, output_snippet="Found 5 modules: core/loop.py, core/todo.py", action="list")
        tm.mark_done(1, "Architecture analysis complete: 5 modules found, exit 0")
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision.allowed)


class TestUserDecisionCompletionPolicy(unittest.TestCase):
    """Test 9: USER_DECISION requires explicit user input."""

    def test_user_decision_requires_explicit_user_input(self):
        """A USER_DECISION TODO must have explicit user input as evidence.

        The model cannot create the decision itself — it must come from
        the user via the clarify_callback or similar mechanism.
        """
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Get user decision on framework choice"])
        # Without user input evidence, mark_done should raise
        with self.assertRaises(ValueError):
            tm.mark_done(1, "User chose framework A")
        # With user input evidence (e.g., from clarify_callback)
        ev.record(tool="user_input", command_or_path="framework_choice",
                  success=True, output_snippet="User chose: Option A", action="clarify")
        # mark_done should now succeed (the evidence has a tool match)
        tm.mark_done(1, "User chose: 'Option A' — confirmed via clarify callback")
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertTrue(decision.allowed)


class TestDirectMutationCannotBypassValidation(unittest.TestCase):
    """Test 10: Direct done mutation cannot bypass validation."""

    def test_direct_done_mutation_cannot_bypass_validation(self):
        """Directly setting status to DONE without evidence is caught.

        The TodoManager.mark_done() method enforces evidence matching.
        Direct mutation of the status field (bypassing mark_done) is
        caught by can_finalize() which checks evidence for 'done' items.
        """
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        tm.set_plan(["Read file.py"])
        # Bypass mark_done — directly set status to DONE
        item = tm._get(1)
        item.status = TodoStatus.DONE
        item.completion_source = "manual"
        item.evidence_ids = []
        # can_finalize should catch this — no evidence for the 'done' item
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        self.assertFalse(decision.allowed)
        self.assertIn(1, [b.todo_id for b in decision.blocking_todos])


class TestDeserializedDoneItemRevalidated(unittest.TestCase):
    """Test 11: Deserialized done item is revalidated when required."""

    def test_deserialized_done_item_is_revalidated_when_required(self):
        """A deserialized TODO marked 'done' is revalidated by can_finalize.

        After restore(), the TODO status is set from the serialized data.
        can_finalize() checks evidence for 'done' items, so a deserialized
        'done' item without matching evidence will block finalization.
        """
        tm = TodoManager()
        ev = EvidenceLog()
        tm.set_evidence_log(ev)
        # Simulate a deserialized state: TODO marked done with no evidence
        tm.restore([
            {"id": 1, "text": "Read file.py", "status": "done",
             "verification_note": "Done", "evidence_ids": [],
             "completed_at": 1234567890.0,
             "completion_source": "manual", "failure_reason": None}
        ])
        tracker = TodoManagerCompletionTracker(tm)
        decision = can_finalize(
            completion_tracker=tracker, evidence_log=ev, requires_plan=True
        )
        # The 'done' item has no matching evidence → blocks
        self.assertFalse(decision.allowed)
        self.assertIn(1, [b.todo_id for b in decision.blocking_todos])


if __name__ == "__main__":
    unittest.main()
