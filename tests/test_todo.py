"""Automated verification suite for core/todo.py (TodoManager, TodoItem, mandatory verification note)."""

import unittest
from core.todo import TodoItem, TodoManager, TodoStatus


class TestTodoManager(unittest.TestCase):
    def setUp(self):
        self.manager = TodoManager()

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
        item = self.manager.mark_done(1, verification_note="py_compile clean")
        self.assertEqual(item.status, TodoStatus.DONE)
        self.assertEqual(item.verification_note, "py_compile clean")

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            self.manager.mark_in_progress(999)


if __name__ == "__main__":
    unittest.main()
