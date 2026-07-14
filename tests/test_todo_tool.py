"""Automated verification suite for TodoWriteTool (tools/todo.py)."""

import unittest
from core.todo import TodoManager, TodoStatus
from tools.todo import TodoWriteTool


class TestTodoWriteTool(unittest.TestCase):
    def setUp(self):
        self.manager = TodoManager()
        self.tool = TodoWriteTool(self.manager)

    def test_plan_action_success(self):
        res = self.tool.execute(action="plan", items=["Task 1", "Task 2"])
        self.assertTrue(res.success)
        self.assertIn("Plan created with 2 items", res.stdout)

    def test_plan_action_missing_items(self):
        res = self.tool.execute(action="plan")
        self.assertFalse(res.success)
        self.assertIn("required", res.stderr)

    def test_update_action_in_progress(self):
        self.tool.execute(action="plan", items=["Task 1"])
        res = self.tool.execute(action="update", item_id=1, status="in_progress")
        self.assertTrue(res.success)
        self.assertIn("in_progress", res.stdout)

    def test_update_action_done_missing_note(self):
        self.tool.execute(action="plan", items=["Task 1"])
        res = self.tool.execute(action="update", item_id=1, status="done", verification_note="")
        self.assertFalse(res.success)
        self.assertIn("Cannot mark TODO #1 done without a verification_note", res.stderr)

    def test_update_action_done_success(self):
        self.tool.execute(action="plan", items=["Task 1"])
        res = self.tool.execute(
            action="update", item_id=1, status="done", verification_note="py_compile clean"
        )
        self.assertTrue(res.success)
        self.assertIn("done", res.stdout)


if __name__ == "__main__":
    unittest.main()
