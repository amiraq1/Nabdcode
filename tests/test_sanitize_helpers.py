"""Unit tests for helpers extracted during the PRIORITY-2 complexity reduction.

These pin the behavior of ``_strip_illegal_control_chars`` (sanitize) and
``StructuralVerifier._assess_token_match`` (evidence) so the refactor that
lowered their parents' cyclomatic complexity stays regression-free.
"""
import unittest

from core.sanitize import _strip_illegal_control_chars
from core.evidence import StructuralVerifier, VerificationResult


class TestStripIllegalControlChars(unittest.TestCase):
    def test_preserves_printable(self):
        self.assertEqual(
            _strip_illegal_control_chars("hello world", preserve_newlines=True,
                                         preserve_tabs=True, keep_color=False),
            "hello world",
        )

    def test_drops_control_category(self):
        # U+0007 (BEL) and U+0001 (control) are in category Cc.
        out = _strip_illegal_control_chars("a\u0007b\u0001c", preserve_newlines=True,
                                           preserve_tabs=True, keep_color=False)
        self.assertEqual(out, "abc")

    def test_preserves_newline_when_requested(self):
        out = _strip_illegal_control_chars("a\nb", preserve_newlines=True,
                                           preserve_tabs=True, keep_color=False)
        self.assertEqual(out, "a\nb")

    def test_drops_newline_when_not_requested(self):
        out = _strip_illegal_control_chars("a\nb", preserve_newlines=False,
                                           preserve_tabs=True, keep_color=False)
        self.assertEqual(out, "ab")

    def test_keeps_color_esc(self):
        out = _strip_illegal_control_chars("\x1b[31mred", preserve_newlines=True,
                                           preserve_tabs=True, keep_color=True)
        self.assertEqual(out, "\x1b[31mred")


class TestAssessTokenMatch(unittest.TestCase):
    def test_pass_on_strong_overlap(self):
        res = StructuralVerifier._assess_token_match(
            {"file_system", "core/_env.py"},
            "the file_system tool read core/_env.py successfully".lower(),
            findings=[],
        )
        self.assertTrue(res.ok)
        self.assertEqual(res.level, "L1")

    def test_fail_on_no_match(self):
        res = StructuralVerifier._assess_token_match(
            {"nonexistent_token_xyz"},
            "completely unrelated evidence text".lower(),
            findings=[],
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.level, "L1")

    def test_technical_anchor_forces_pass(self):
        # Single technical anchor (contains '/') present in evidence.
        res = StructuralVerifier._assess_token_match(
            {"core/config.py"},
            "core/config.py was read".lower(),
            findings=[],
        )
        self.assertTrue(res.ok)


if __name__ == "__main__":
    unittest.main()
