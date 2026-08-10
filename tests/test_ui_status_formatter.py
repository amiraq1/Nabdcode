"""tests/test_ui_status_formatter.py — UX-1: Arabic status message formatter.

Verifies that ``format_status_message`` produces correct Arabic strings
for each pipeline phase and correctly embeds the step count when provided.
"""

import pytest

from ui.repl_termux import format_status_message


class TestFormatStatusMessage:
    """Tests for the UX-1 Arabic status message formatter."""

    def test_thinking_phase(self):
        """Phase 'thinking' maps to 'جاري التفكير'."""
        msg = format_status_message("thinking")
        assert "جاري التفكير" in msg

    def test_tools_phase(self):
        """Phase 'tools' maps to 'جاري تشغيل الأدوات'."""
        msg = format_status_message("tools")
        assert "جاري تشغيل الأدوات" in msg

    def test_generating_phase(self):
        """Phase 'generating' maps to 'جاري الإنشاء'."""
        msg = format_status_message("generating")
        assert "جاري الإنشاء" in msg

    def test_done_phase(self):
        """Phase 'done' maps to 'اكتمل'."""
        msg = format_status_message("done")
        assert "اكتمل" in msg

    def test_unknown_phase_falls_back(self):
        """Unknown phase returns the raw phase name."""
        msg = format_status_message("unknown_phase")
        assert "unknown_phase" in msg

    def test_step_count_embedded(self):
        """Step count appears as 'الخطوة N' in the message."""
        msg = format_status_message("thinking", step=3)
        assert "الخطوة 3" in msg

    def test_step_count_zero_omitted(self):
        """Step 0 (or None) does not show a step number."""
        msg = format_status_message("thinking", step=0)
        assert "الخطوة" not in msg

    def test_step_count_none_omitted(self):
        """None step does not show a step number."""
        msg = format_status_message("thinking", step=None)
        assert "الخطوة" not in msg

    def test_negative_step_omitted(self):
        """Negative step does not show a step number."""
        msg = format_status_message("thinking", step=-1)
        assert "الخطوة" not in msg

    def test_ellipsis_suffix(self):
        """Message ends with '...' when step is omitted."""
        msg = format_status_message("thinking")
        assert msg.endswith("...")

    def test_ellipsis_suffix_with_step(self):
        """Message ends with step count in parentheses when step is provided."""
        msg = format_status_message("thinking", step=5)
        assert msg.endswith("(الخطوة 5)")

    def test_full_message_thinking_with_step(self):
        """Full message for thinking with step 1."""
        msg = format_status_message("thinking", step=1)
        assert msg == "جاري التفكير... (الخطوة 1)"

    def test_full_message_tools_with_step(self):
        """Full message for tools with step 2."""
        msg = format_status_message("tools", step=2)
        assert msg == "جاري تشغيل الأدوات... (الخطوة 2)"

    def test_full_message_generating_with_step(self):
        """Full message for generating with step 3."""
        msg = format_status_message("generating", step=3)
        assert msg == "جاري الإنشاء... (الخطوة 3)"

    def test_full_message_done_with_step(self):
        """Full message for done with step 4."""
        msg = format_status_message("done", step=4)
        assert msg == "اكتمل... (الخطوة 4)"

    def test_step_as_string(self):
        """Step count passed as string is accepted."""
        msg = format_status_message("thinking", step="7")
        assert "الخطوة 7" in msg
