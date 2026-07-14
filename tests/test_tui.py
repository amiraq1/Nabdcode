"""Automated verification suite for stream-based TUI module core/tui.py."""

import io
import unittest
from unittest.mock import patch
from core.tui import print_badge, print_thought, print_status_bar, render_mock_execution


class TestStreamTUI(unittest.TestCase):
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_badge(self, mock_stdout):
        print_badge("READ", "engine/state.py")
        output = mock_stdout.getvalue()
        self.assertIn("READ", output)
        self.assertIn("engine/state.py", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_delegate_badge(self, mock_stdout):
        print_badge("DELEGATE", "Manager handing off task to Executor...")
        output = mock_stdout.getvalue()
        self.assertIn("DELEGATE", output)
        self.assertIn("Manager handing off task to Executor...", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_thought(self, mock_stdout):
        print_thought(2)
        output = mock_stdout.getvalue()
        self.assertIn("* Thought for 2 second [ctrl+o to expand]", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_status_bar(self, mock_stdout):
        print_status_bar("Contemplating", "47.1k")
        output = mock_stdout.getvalue()
        self.assertIn("Contemplating...", output)
        self.assertIn("47.1k", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_render_mock_execution(self, mock_stdout):
        render_mock_execution("test task")
        output = mock_stdout.getvalue()
        self.assertIn("READ", output)
        self.assertIn("EDIT", output)
        self.assertIn("TODOS", output)
        self.assertIn("DELEGATE", output)



if __name__ == "__main__":
    unittest.main()
