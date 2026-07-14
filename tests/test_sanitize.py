"""tests/test_sanitize.py — Comprehensive verification suite for stream & string sanitization.

Verifies:
  1. Adversarial ANSI CSI, OSC, DCS, and single escape sequences removal.
  2. Null bytes (0x00), Backspace (0x08), BEL (0x07) removal.
  3. Unicode, multi-byte, and Emoji preservation.
  4. Integration with Parser (normalize & validate_tool_call).
  5. Integration with Subprocess safe_execute_command output.
  6. Integration with Renderer (agent_text, stream_chunk, tool_end).
  7. Deterministic O(n) linear performance on large payloads.
"""

import sys
import time
import unittest
from io import StringIO

from core.sanitize import sanitize, strip_ansi_sequences
from core.parser import normalize, validate_tool_call
from core.utils import safe_execute_command
from engine.renderer import Renderer


class TestSanitizeCore(unittest.TestCase):
    def test_strip_csi_colors_and_cursor(self):
        dirty = "Hello \x1b[31mRed\x1b[0m World \x1b[2J\x1b[H!"
        clean = sanitize(dirty)
        self.assertEqual(clean, "Hello Red World !")

    def test_strip_osc_and_dcs(self):
        dirty = "\x1b]0;Pwned Title\x07Welcome\x1bPtest_dcs\x1b\\ Home"
        clean = sanitize(dirty)
        self.assertEqual(clean, "Welcome Home")

    def test_strip_null_bs_bel(self):
        dirty = "abc\x00def\x08ghi\x07jkl"
        clean = sanitize(dirty)
        self.assertEqual(clean, "abcdefghijkl")

    def test_unicode_and_emoji_preservation(self):
        text = "مرحبا بالعالم 🌍 Python 🐍 #Nabdcode"
        clean = sanitize(text)
        self.assertEqual(clean, text)

    def test_newline_and_tab_preservation(self):
        dirty = "Line 1\r\nLine 2\tTabbed\x1b[32m Green\x1b[0m"
        clean = sanitize(dirty, preserve_newlines=True, preserve_tabs=True)
        self.assertEqual(clean, "Line 1\nLine 2\tTabbed Green")

    def test_linear_performance(self):
        # Build a 100k character payload with repeated escape sequences
        dirty = ("Payload \x1b[31mDATA\x1b[0m \x00\x07" * 5000)
        start = time.perf_counter()
        clean = sanitize(dirty)
        elapsed = time.perf_counter() - start
        self.assertNotIn("\x1b", clean)
        self.assertNotIn("\x00", clean)
        self.assertLess(elapsed, 0.5, f"Sanitization took {elapsed:.3f}s (must be fast linear scan)")


class TestSubsystemIntegration(unittest.TestCase):
    def test_parser_normalize_strips_ansi(self):
        dirty = "Input \x1b[2J\x1b[H\x1b[31mAlert\x1b[0m"
        clean = normalize(dirty)
        self.assertEqual(clean, "Input Alert")

    def test_parser_validate_tool_call_with_ansi_payload(self):
        dirty_json = '{"tool": "file_system", "args": {"path": "test.txt", "action": "\x1b[31mread\x1b[0m"}}'
        res = validate_tool_call(dirty_json)
        self.assertTrue(res.ok, f"Expected valid tool call after sanitization, got {res.error}")

    def test_subprocess_safe_execute_command_sanitization(self):
        code, out, err = safe_execute_command("python3 tests/helper_ansi_emitter.py")
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x00", out)
        self.assertIn("Hello World", out)

    def test_renderer_stream_chunk_and_agent_text_sanitization(self):
        r = Renderer()
        old_stdout = sys.stdout
        buf = StringIO()
        try:
            sys.stdout = buf
            r.stream_chunk("Token \x1b[2J\x1b[HAlert\x1b[0m")
            r.agent_text("Response \x1b[31mRed\x1b[0m")
            r.flush()
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertNotIn("\x1b[2J", output)
        self.assertNotIn("\x1b[H", output)
        self.assertIn("Token Alert", output)
        self.assertIn("Response Red", output)

    def test_format_tool_result_output(self):
        from core.sanitize import format_tool_result_output
        raw = "Line1\x1b[31mRed\x1b[0m\nLine2"
        res = format_tool_result_output(raw, max_length=10)
        self.assertNotIn("\x1b[31m", res)
        self.assertIn("[TRUNCATED TOOL RESULT]", res)

    def test_has_goal_complete_signal(self):
        from core.sanitize import has_goal_complete_signal
        self.assertTrue(has_goal_complete_signal("Done! <!-- GOAL_COMPLETE -->"))
        self.assertTrue(has_goal_complete_signal("Cancelled <!-- GOAL_CANCELLED -->"))
        self.assertTrue(has_goal_complete_signal("Task done\n<goal-complete/>\n"))
        self.assertFalse(has_goal_complete_signal("embedded <goal-complete/> not standalone line"))
        self.assertFalse(has_goal_complete_signal("Still working..."))

    def test_strip_goal_complete_marker(self):
        from core.sanitize import strip_goal_complete_marker
        raw = "All tasks completed.\n\n<goal-complete/>\n"
        cleaned = strip_goal_complete_marker(raw)
        self.assertEqual(cleaned, "All tasks completed.")
        self.assertNotIn("<goal-complete/>", cleaned)

    def test_fix_arabic_reversal(self):
        from core.sanitize import fix_arabic_reversal
        self.assertEqual(fix_arabic_reversal("ي ع د و ت س م م ح ف"), "فحص مستودعي")
        self.assertEqual(fix_arabic_reversal("فحص مستودعي"), "فحص مستودعي")
        self.assertEqual(fix_arabic_reversal("/goal check"), "/goal check")


if __name__ == "__main__":
    unittest.main()
