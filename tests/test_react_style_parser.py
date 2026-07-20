"""Tests for the forgiving ReAct-style parser fallback in core.parser.

Small/fallback models (e.g. Llama-3.1) sometimes emit ReAct-style actions
(``SEARCH "query"`` / ``FINAL_ANSWER "text"``) instead of the canonical JSON
tool call. The forgiving parser must recover these so the model does not spin
into a frustration loop.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.app_context as _app_context
_app_context.AppContext.build()

from core.parser import extract_command  # noqa: E402


class TestReactStyleParser(unittest.TestCase):
    def test_search_with_quotes(self):
        tc = extract_command('SEARCH "python 3.12 new feature"')
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "python 3.12 new feature")

    def test_search_without_quotes(self):
        tc = extract_command("SEARCH python 3.12 new feature")
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "python 3.12 new feature")

    def test_search_with_brackets(self):
        tc = extract_command('SEARCH ["latest python 3.12 feature"]')
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "latest python 3.12 feature")

    def test_final_answer_with_quotes(self):
        tc = extract_command('FINAL_ANSWER "no big features"')
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "final_answer")
        self.assertEqual(tc.args["answer"], "no big features")

    def test_final_answer_prose_colon(self):
        tc = extract_command("Final Answer: the answer is 42")
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "final_answer")
        self.assertEqual(tc.args["answer"], "the answer is 42")

    def test_canonical_json_still_preferred(self):
        tc = extract_command('{"tool": "web_search", "args": {"query": "xxx"}}')
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "xxx")
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "x" * 3)

    def test_plain_prose_returns_none(self):
        tc = extract_command("I think we should look into this further.")
        self.assertIsNone(tc)

    def test_action_json_interception(self):
        text = """
Thought: I should search for documentation.
Action: {
  "tool": "web_search",
  "args": {"query": "python 3.12"}
}
Observation: [hallucinated observation...]
"""
        tc = extract_command(text)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "python 3.12")

    def test_action_json_with_name_alias(self):
        text = """
Action: {
  "name": "web_search",
  "parameters": {"query": "python 3.12"}
}
Observation: [hallucinated observation...]
"""
        tc = extract_command(text)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "python 3.12")

    def test_action_json_with_code_fence(self):
        text = """
Action:
```json
{"tool": "execute_shell", "args": {"command": "ls"}}
```
Observation: file1 file2
"""
        tc = extract_command(text)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "execute_shell")
        self.assertEqual(tc.args["command"], "ls")


if __name__ == "__main__":
    unittest.main()
