"""Automated verification suite for render_todos in engine/renderer.py."""

import unittest
from core.todo import TodoItem, TodoStatus
from engine.renderer import Renderer


class TestRendererTodos(unittest.TestCase):
    def setUp(self):
        self.renderer = Renderer()

    def test_render_todos_append_only(self):
        items = [
            TodoItem(id=1, text="Check syntax", status=TodoStatus.DONE),
            TodoItem(id=2, text="Run tests", status=TodoStatus.IN_PROGRESS),
            TodoItem(id=3, text="Deploy", status=TodoStatus.PENDING),
        ]
        self.renderer.render_todos(items)
        self.assertEqual(len(self.renderer._lines), 4)
        self.assertIn("TODOS [1/3]", self.renderer._lines[0])
        self.assertIn("Check syntax", self.renderer._lines[1])
        self.assertIn("Run tests", self.renderer._lines[2])
        self.assertIn("Deploy", self.renderer._lines[3])


if __name__ == "__main__":
    unittest.main()
