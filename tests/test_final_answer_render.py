"""Regression tests for the TUI final_answer rendering fix (UI-layer only).

The ExecutionLoop terminates casual chat via the smolagents ``final_answer``
convention, leaving the raw tool-call JSON as the last assistant message.
main._extract_final_answer_text must unwrap it to clean text for display
WITHOUT touching core state or altering non-final_answer rendering.
"""

import unittest

import main


class TestExtractFinalAnswerText(unittest.TestCase):
    def test_unwraps_final_answer_json(self):
        raw = '{"tool": "final_answer", "args": {"answer": "Hi there! How can I help?"}}'
        self.assertEqual(
            main._extract_final_answer_text(raw),
            "Hi there! How can I help?",
        )

    def test_preserves_plain_prose(self):
        prose = "The repository has 3 Python files under src/."
        self.assertEqual(main._extract_final_answer_text(prose), prose)

    def test_preserves_prose_with_embedded_json(self):
        prose = 'Sure! Here is the config: {"key": "value"} hope that helps.'
        self.assertEqual(main._extract_final_answer_text(prose), prose)

    def test_other_tool_json_falls_back(self):
        raw = '{"tool": "execute_shell", "args": {"command": "ls"}}'
        self.assertEqual(main._extract_final_answer_text(raw), raw)

    def test_malformed_json_falls_back(self):
        raw = '{"tool": "final_answer", "args": NOT VALID'
        self.assertEqual(main._extract_final_answer_text(raw), raw)

    def test_final_answer_missing_args_falls_back(self):
        raw = '{"tool": "final_answer"}'
        self.assertEqual(main._extract_final_answer_text(raw), raw)

    def test_final_answer_non_string_answer_falls_back(self):
        raw = '{"tool": "final_answer", "args": {"answer": 42}}'
        self.assertEqual(main._extract_final_answer_text(raw), raw)

    def test_empty_input_unchanged(self):
        self.assertEqual(main._extract_final_answer_text(""), "")
        self.assertEqual(main._extract_final_answer_text("   "), "   ")

    def test_multiline_answer_preserved(self):
        raw = '{"tool": "final_answer", "args": {"answer": "Line one\\nLine two"}}'
        self.assertEqual(
            main._extract_final_answer_text(raw),
            "Line one\nLine two",
        )


if __name__ == "__main__":
    unittest.main()
