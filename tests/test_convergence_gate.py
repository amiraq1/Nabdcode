"""Comprehensive convergence gate, evidence-linking, RTL, and footer tests.

Covers all 15 required test cases:
  1.  test_final_answer_blocked_with_pending_todo
  2.  test_final_answer_blocked_with_in_progress_todo
  3.  test_final_answer_allowed_when_all_todos_done
  4.  test_final_answer_reports_blocked_or_skipped_todos
  5.  test_budget_exhaustion_returns_partial_not_complete
  6.  test_read_todo_requires_matching_successful_read_event
  7.  test_failed_tool_call_cannot_complete_todo
  8.  test_verify_todo_requires_verification_evidence
  9.  test_todo_and_event_view_cannot_diverge
  10. test_architectural_claims_are_scoped_to_available_evidence
  11. test_arabic_input_preserves_original_unicode
  12. test_mixed_arabic_and_file_path_rendering
  13. test_ansi_does_not_break_display_width
  14. test_edit_footer_hidden_without_pending_edits
  15. test_edit_footer_resets_between_sessions
"""

import unittest
from unittest.mock import MagicMock

from core.convergence_gate import (
    can_finalize,
    FinalizationDecision,
    TodoEvidenceLink,
    classify_claim,
)
from core.todo import TodoManager, TodoItem, TodoStatus
from core.evidence import EvidenceLog, EvidenceRecord
from core.text_utils import (
    display_width,
    safe_display,
    preserve_unicode_order,
    is_arabic,
    wrap_text,
    strip_ansi,
)


class TestFinalAnswerBlockedWithPendingTodo(unittest.TestCase):
    """Test 1: FINAL ANSWER blocked when a TODO is pending."""

    def test_final_answer_blocked_with_pending_todo(self):
        mgr = TodoManager()
        mgr.set_plan(["Read core/loop.py", "Verify the fix", "Write tests"])
        decision = can_finalize(mgr, EvidenceLog())
        self.assertFalse(decision.allowed)
        self.assertGreater(len(decision.blocking_todos), 0)
        self.assertIn("pending", decision.blocked_reason.lower())


class TestFinalAnswerBlockedWithInProgressTodo(unittest.TestCase):
    """Test 2: FINAL ANSWER blocked when a TODO is in_progress."""

    def test_final_answer_blocked_with_in_progress_todo(self):
        mgr = TodoManager()
        mgr.set_plan(["Read core/loop.py", "Verify the fix", "Write tests"])
        mgr.mark_in_progress(1)
        decision = can_finalize(mgr, EvidenceLog())
        self.assertFalse(decision.allowed)
        self.assertGreater(len(decision.blocking_todos), 0)
        self.assertIn("in_progress", decision.blocked_reason.lower())


class TestFinalAnswerAllowedWhenAllTodosDone(unittest.TestCase):
    """Test 3: FINAL ANSWER allowed when all TODOs are done with evidence."""

    def test_final_answer_allowed_when_all_todos_done(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Read core/loop.py", "Verify the fix"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/loop.py",
            success=True,
            output_snippet="from __future__ import annotations",
            action="read",
        )
        mgr.mark_done(1, "py_compile: 0 errors on core/loop.py")

        ev_log.record(
            tool="execute_shell",
            command_or_path="python3 -m pytest tests/test_loop.py -v",
            success=True,
            output_snippet="15 passed in 2.3s",
            action="",
        )
        mgr.mark_done(2, "pytest: 15 passed in 2.3s")

        decision = can_finalize(mgr, ev_log)
        self.assertTrue(decision.allowed)
        self.assertEqual(len(decision.blocking_todos), 0)


class TestFinalAnswerReportsBlockedOrSkippedTodos(unittest.TestCase):
    """Test 4: FINAL ANSWER reports blocked/skipped TODOs correctly."""

    def test_final_answer_reports_blocked_or_skipped_todos(self):
        mgr = TodoManager()
        mgr.set_plan(["Read core/loop.py", "Verify the fix", "Write tests"])
        mgr.mark_skipped(2, "Not needed for this task")
        mgr.mark_blocked(3, "Waiting for user input")
        decision = can_finalize(mgr, EvidenceLog())
        self.assertFalse(decision.allowed)
        blocking_ids = [b.todo_id for b in decision.blocking_todos]
        self.assertIn(1, blocking_ids)
        self.assertNotIn(2, blocking_ids)
        self.assertNotIn(3, blocking_ids)

    def test_final_answer_allows_when_skipped_and_blocked_have_reasons(self):
        mgr = TodoManager()
        mgr.set_plan(["Task A", "Task B"])
        mgr.mark_skipped(1, "Not needed")
        mgr.mark_blocked(2, "Waiting for input")
        decision = can_finalize(mgr, EvidenceLog())
        self.assertTrue(decision.allowed)


class TestBudgetExhaustionReturnsPartial(unittest.TestCase):
    """Test 5: Budget exhaustion returns PARTIAL, not complete."""

    def test_budget_exhaustion_returns_partial_not_complete(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Read core/loop.py", "Verify the fix", "Write tests"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/loop.py",
            success=True,
            output_snippet="content",
            action="read",
        )
        mgr.mark_done(1, "py_compile: 0 errors on core/loop.py")

        decision = can_finalize(mgr, ev_log, budget_exhausted=True)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.partial)
        self.assertIn("Budget", decision.blocked_reason)
        self.assertIn("incomplete", decision.blocked_reason.lower())


class TestReadTodoRequiresMatchingSuccessfulReadEvent(unittest.TestCase):
    """Test 6: READ TODO requires a matching successful read event."""

    def test_read_todo_requires_matching_successful_read_event(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Read core/bootstrap.py"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/loop.py",
            success=True,
            output_snippet="content",
            action="read",
        )

        with self.assertRaises(ValueError) as ctx:
            mgr.mark_done(1, "py_compile OK on core/bootstrap.py")
        self.assertIn("no matching evidence", str(ctx.exception).lower())

    def test_read_todo_passes_with_matching_read_event(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Read core/bootstrap.py"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/bootstrap.py",
            success=True,
            output_snippet="content",
            action="read",
        )

        item = mgr.mark_done(1, "py_compile OK on core/bootstrap.py")
        self.assertEqual(item.status, TodoStatus.DONE)
        self.assertGreater(len(item.evidence_ids), 0)


class TestFailedToolCallCannotCompleteTodo(unittest.TestCase):
    """Test 7: A failed tool call cannot complete a TODO."""

    def test_failed_tool_call_cannot_complete_todo(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Read core/bootstrap.py"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/bootstrap.py",
            success=False,
            output_snippet="File not found",
            action="read",
        )

        with self.assertRaises(ValueError):
            mgr.mark_done(1, "File not found error observed")

    def test_failed_tool_call_with_successful_evidence_can_complete(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Read core/bootstrap.py"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/bootstrap.py",
            success=False,
            output_snippet="File not found",
            action="read",
        )
        ev_log.record(
            tool="file_system",
            command_or_path="core/bootstrap.py",
            success=True,
            output_snippet="content found",
            action="read",
        )

        item = mgr.mark_done(1, "File read successfully, 0 errors on core/bootstrap.py")
        self.assertEqual(item.status, TodoStatus.DONE)


class TestVerifyTodoRequiresVerificationEvidence(unittest.TestCase):
    """Test 8: VERIFY TODO requires actual verification evidence, not just file read."""

    def test_verify_todo_requires_verification_evidence(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Verify the fix works"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/loop.py",
            success=True,
            output_snippet="content",
            action="read",
        )

        with self.assertRaises(ValueError):
            mgr.mark_done(1, "Verified by reading the code")

    def test_verify_todo_passes_with_test_evidence(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Verify the fix works"])

        ev_log.record(
            tool="execute_shell",
            command_or_path="python3 -m pytest tests/test_loop.py -v",
            success=True,
            output_snippet="15 passed in 2.3s",
            action="",
        )

        item = mgr.mark_done(1, "pytest: 15 passed in 2.3s")
        self.assertEqual(item.status, TodoStatus.DONE)


class TestTodoAndEventViewCannotDiverge(unittest.TestCase):
    """Test 9: TODO state and event view cannot diverge."""

    def test_todo_and_event_view_cannot_diverge(self):
        mgr = TodoManager()
        ev_log = EvidenceLog()
        mgr.set_evidence_log(ev_log)
        mgr.set_plan(["Read core/loop.py"])

        ev_log.record(
            tool="file_system",
            command_or_path="core/loop.py",
            success=True,
            output_snippet="content",
            action="read",
        )

        item = mgr.mark_done(1, "py_compile: 0 errors on core/loop.py")

        ev_records = ev_log.get_records()
        ev_ids = {r.evidence_id for r in ev_records if r.success}
        todo_ev_ids = set(item.evidence_ids)

        for eid in todo_ev_ids:
            self.assertIn(eid, ev_ids, f"TODO evidence_id {eid} not in EvidenceLog")

        serialized = mgr.to_serializable()
        self.assertEqual(serialized[0]["status"], "done")
        self.assertEqual(serialized[0]["evidence_ids"], list(item.evidence_ids))

    def test_todo_deleted_before_finalize_is_treated_as_unknown(self):
        elog = EvidenceLog()
        elog.record(tool="execute_shell", command_or_path="run_tests", success=True,
                     output_snippet="15 passed in 2.3s on file_b.py")
        mgr = TodoManager(evidence_log=elog)
        mgr.set_plan(["Task A", "Task B", "Task C"])
        mgr.mark_in_progress(1)
        mgr.mark_done(2, "15 passed in 2.3s on file_b.py")

        mgr._items = mgr._items[:2]

        decision = can_finalize(mgr, EvidenceLog())
        self.assertFalse(decision.allowed)


class TestArchitecturalClaimsScopedToAvailableEvidence(unittest.TestCase):
    """Test 10: Architectural claims are scoped to available evidence."""

    def test_architectural_claims_are_scoped_to_available_evidence(self):
        ev_log = EvidenceLog()
        ev_log.record(
            tool="file_system",
            command_or_path="main.py",
            success=True,
            output_snippet="def main():",
            action="read",
        )
        ev_log.record(
            tool="file_system",
            command_or_path="pyproject.toml",
            success=True,
            output_snippet="name = nabd-os",
            action="read",
        )

        claim = "The repository contains a file core/bootstrap.py with 42 functions."
        classification = classify_claim(claim, ev_log.get_records())
        self.assertEqual(classification, "UNVERIFIED")

    def test_claim_with_direct_evidence_is_observed(self):
        ev_log = EvidenceLog()
        ev_log.record(
            tool="file_system",
            command_or_path="pyproject.toml",
            success=True,
            output_snippet='name = "nabd-os"',
            action="read",
        )

        claim = 'The project name is "nabd-os".'
        classification = classify_claim(claim, ev_log.get_records())
        self.assertEqual(classification, "OBSERVED")

    def test_claim_with_partial_evidence_is_inferred(self):
        ev_log = EvidenceLog()
        ev_log.record(
            tool="file_system",
            command_or_path="pyproject.toml",
            success=True,
            output_snippet='name = "nabd-os"',
            action="read",
        )

        claim = "The project name is nabd-os and core/bootstrap.py has 42 functions."
        classification = classify_claim(claim, ev_log.get_records())
        self.assertEqual(classification, "INFERRED")


class TestArabicInputPreservesOriginalUnicode(unittest.TestCase):
    """Test 11: Arabic input preserves original Unicode order."""

    def test_arabic_input_preserves_original_unicode(self):
        text = "افتح الملف الرئيسي ثم استخدم الدوال المناسبة"
        preserved = preserve_unicode_order(text)
        self.assertEqual(preserved, text)

    def test_mixed_arabic_english_preserves_order(self):
        text = "افتح main.py ثم core/utils.py"
        preserved = preserve_unicode_order(text)
        self.assertEqual(preserved, text)

    def test_arabic_with_numbers_preserves_order(self):
        text = "اقرأ 3 ملفات ثم اكتب التقرير"
        preserved = preserve_unicode_order(text)
        self.assertEqual(preserved, text)

    def test_arabic_with_punctuation_preserves_order(self):
        text = "هل يعمل؟ نعم، جيد."
        preserved = preserve_unicode_order(text)
        self.assertEqual(preserved, text)

    def test_english_text_unchanged(self):
        text = "Read the main.py file and check the output"
        preserved = preserve_unicode_order(text)
        self.assertEqual(preserved, text)

    def test_fix_arabic_reversal_is_noop(self):
        from core.sanitize import fix_arabic_reversal
        text = "افتح main.py ثم core/utils.py"
        self.assertEqual(fix_arabic_reversal(text), text)


class TestMixedArabicAndFilePathRendering(unittest.TestCase):
    """Test 12: Mixed Arabic and file path rendering."""

    def test_mixed_arabic_and_file_path_rendering(self):
        text = "افتح main.py ثم core/utils.py"
        displayed = safe_display(text)
        self.assertIn("main.py", displayed)
        self.assertIn("core/utils.py", displayed)
        self.assertIn("افتح", displayed)

    def test_mixed_arabic_english_with_ansi(self):
        text = "\x1b[31mمرحبا\x1b[0m World"
        displayed = safe_display(text)
        self.assertIn("مرحبا", displayed)
        self.assertIn("World", displayed)

    def test_arabic_full_text_rendering(self):
        text = "هذا نص عربي كامل للتجربة"
        displayed = safe_display(text)
        self.assertIn("هذا نص عربي كامل للتجربة", displayed)


class TestAnsiDoesNotBreakDisplayWidth(unittest.TestCase):
    """Test 13: ANSI codes do not break display width calculation."""

    def test_ansi_does_not_break_display_width(self):
        text_with_ansi = "\x1b[31mHello\x1b[0m World"
        text_without_ansi = "Hello World"
        self.assertEqual(display_width(text_with_ansi), display_width(text_without_ansi))

    def test_display_width_with_arabic(self):
        text = "مرحبا"
        width = display_width(text)
        self.assertEqual(width, len(text))

    def test_display_width_with_emoji(self):
        text = "🌍"
        width = display_width(text)
        self.assertEqual(width, 2)

    def test_display_width_with_mixed_content(self):
        text = "\x1b[31mمرحبا\x1b[0m 🌍"
        width = display_width(text)
        # 5 Arabic chars (5) + 1 space (1) + 1 emoji (2) = 8
        self.assertEqual(width, 8)

    def test_strip_ansi_removes_codes(self):
        text = "\x1b[31mHello\x1b[0m World"
        stripped = strip_ansi(text)
        self.assertEqual(stripped, "Hello World")

    def test_wrap_text_with_ansi(self):
        text = "\x1b[31mHello World\x1b[0m"
        wrapped = wrap_text(text, 5)
        self.assertIsInstance(wrapped, list)
        self.assertGreater(len(wrapped), 0)


class TestEditFooterHiddenWithoutPendingEdits(unittest.TestCase):
    """Test 14: Edit footer hidden when no pending edits."""

    def test_edit_footer_hidden_without_pending_edits(self):
        import core.accept_edits_state as _state
        _state.reset_session()
        _state._accept_edits_enabled = True
        self.assertFalse(_state.has_pending_edits())

    def test_edit_footer_visible_with_pending_edits(self):
        import core.accept_edits_state as _state
        from core.accept_edits_state import PendingEdit
        _state.reset_session()
        _state._accept_edits_pending.append(PendingEdit(
            path="test.py",
            resolved_path="/test.py",
            old_content="old",
            new_content="new",
            diff="diff",
            additions=1,
            removals=1,
        ))
        _state._accept_edits_enabled = True
        self.assertTrue(_state.has_pending_edits())
        self.assertEqual(_state.pending_edit_count(), 1)
        _state.reset_session()

    def test_edit_footer_hidden_when_mode_disabled(self):
        import core.accept_edits_state as _state
        from core.accept_edits_state import PendingEdit
        _state.reset_session()
        _state._accept_edits_pending.append(PendingEdit(
            path="test.py",
            resolved_path="/test.py",
            old_content="old",
            new_content="new",
            diff="diff",
            additions=1,
            removals=1,
        ))
        _state._accept_edits_enabled = False
        self.assertFalse(_state.has_pending_edits())
        _state.reset_session()


class TestEditFooterResetsBetweenSessions(unittest.TestCase):
    """Test 15: Edit footer resets between sessions."""

    def test_edit_footer_resets_between_sessions(self):
        import core.accept_edits_state as _state
        from core.accept_edits_state import PendingEdit
        _state._accept_edits_pending.append(PendingEdit(
            path="test.py",
            resolved_path="/test.py",
            old_content="old",
            new_content="new",
            diff="diff",
            additions=1,
            removals=1,
        ))
        _state._accept_edits_enabled = True

        _state.reset_session()

        self.assertEqual(_state.pending_edit_count(), 0)
        self.assertFalse(_state.has_pending_edits())

    def test_edit_footer_does_not_leak_between_tasks(self):
        import core.accept_edits_state as _state
        from core.accept_edits_state import PendingEdit
        _state._accept_edits_pending.append(PendingEdit(
            path="task1.py",
            resolved_path="/task1.py",
            old_content="old",
            new_content="new",
            diff="diff",
            additions=1,
            removals=1,
        ))
        _state._accept_edits_enabled = True

        _state.reset_session()

        self.assertEqual(_state.pending_edit_count(), 0)
        self.assertFalse(_state.has_pending_edits())


if __name__ == "__main__":
    unittest.main()
