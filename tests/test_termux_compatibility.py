"""tests/test_termux_compatibility.py — TERM-1: Arabic rendering fallback.

Verifies that:
  • ``render_arabic`` works without arabic-reshaper/bidi (graceful fallback)
  • ``has_bidi_support`` reflects the actual availability
  • the data layer never reorders Arabic text (bidi-isolation only)
"""

from __future__ import annotations

from unittest.mock import patch

from core import text_utils
from core.text_utils import render_arabic, safe_display, is_arabic, has_bidi_support


class TestTermuxArabicFallback:
    def test_graceful_degradation_without_bidi(self):
        """render_arabic works when bidi packages are absent (Termux case)."""
        with patch.object(text_utils, "_HAS_BIDI", False):
            result = render_arabic("مرحبا بالعالم")
            assert "مرحبا" in result

    def test_no_crash_on_empty_text(self):
        """render_arabic handles empty/None-ish input without raising."""
        assert render_arabic("") == ""

    def test_has_bidi_support_flag(self):
        """has_bidi_support returns a bool reflecting import availability."""
        assert isinstance(has_bidi_support(), bool)

    def test_arabic_text_rendered_correctly_if_bidi_present(self):
        """When bidi IS available, Arabic is shaped and reordered."""
        fake_reshaped = "مرحبا"  # stand-in for reshape output
        fake_display = fake_reshaped

        class FakeReshaper:
            @staticmethod
            def reshape(text):
                return text

        class FakeBidi:
            @staticmethod
            def get_display(text):
                return fake_display

        with patch.object(text_utils, "_HAS_BIDI", True), \
             patch.object(text_utils, "arabic_reshaper", FakeReshaper), \
             patch.object(text_utils, "get_display", FakeBidi.get_display):
            result = render_arabic("مرحبا")
            assert result == fake_display

    def test_safe_display_preserves_original_order(self):
        """safe_display only adds isolation marks; it never reorders text."""
        text = "مرحبا بالعالم"
        out = safe_display(text)
        # RLM/LRM marks are stripped before comparison
        stripped = out.replace("\u200E", "").replace("\u200F", "")
        assert stripped == text

    def test_is_arabic_detection(self):
        """is_arabic detects Arabic text and rejects Latin."""
        assert is_arabic("مرحبا بالعالم") is True
        assert is_arabic("hello world") is False

    def test_render_arabic_on_latin_unchanged(self):
        """Latin text passes through render_arabic unmodified."""
        with patch.object(text_utils, "_HAS_BIDI", False):
            assert render_arabic("hello world") == safe_display("hello world")
