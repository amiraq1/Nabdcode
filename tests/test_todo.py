"""Automated verification suite for core/todo.py (TodoManager, TodoItem, mandatory verification note)."""

import unittest
from core.evidence import EvidenceLog
from core.todo import TodoItem, TodoManager, TodoStatus


class TestTodoManager(unittest.TestCase):
    def setUp(self):
        self.evidence_log = EvidenceLog()
        self.manager = TodoManager(evidence_log=self.evidence_log)

    def test_set_plan(self):
        items = self.manager.set_plan(["Step 1: Check syntax", "Step 2: Run tests"])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].id, 1)
        self.assertEqual(items[0].status, TodoStatus.PENDING)

    def test_mark_in_progress(self):
        self.manager.set_plan(["Step 1"])
        item = self.manager.mark_in_progress(1)
        self.assertEqual(item.status, TodoStatus.IN_PROGRESS)

    def test_mark_done_requires_verification_note(self):
        self.manager.set_plan(["Step 1"])
        with self.assertRaises(ValueError):
            self.manager.mark_done(1, verification_note="")

    def test_mark_done_success(self):
        self.manager.set_plan(["Step 1"])
        self.evidence_log.record(
            tool="execute_shell", command_or_path="py_compile",
            success=True, output_snippet="py_compile clean, 0 errors",
        )
        item = self.manager.mark_done(1, verification_note="py_compile clean")
        self.assertEqual(item.status, TodoStatus.DONE)
        self.assertEqual(item.verification_note, "py_compile clean")

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            self.manager.mark_in_progress(999)

    def test_mark_done_no_evidence_log_raises(self):
        """mark_done without evidence_log must raise ValueError."""
        mgr = TodoManager()  # no evidence_log
        mgr.set_plan(["Step X"])
        with self.assertRaises(ValueError):
            mgr.mark_done(1, verification_note="done")


if __name__ == "__main__":
    unittest.main()
