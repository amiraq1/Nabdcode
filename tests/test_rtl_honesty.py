"""tests/test_rtl_honesty.py — Am+8 D-6: no name may promise bidi repair.

This file is the SOLE permitted mention of the two retired names. They are
written in full, never split and never exec'd: a guard that hides from grep
disables the audit tool the whole repository depends on. Both were no-ops
whose docstrings promised detection and repair of reversed Arabic text.
"""
from __future__ import annotations

import core.sanitize
import core.text_utils

from tests.support.render import make_console
from ui.widgets.tool_result import ToolResultWidget


def test_no_name_promises_bidi_repair() -> None:
    """The lying names must not exist on their modules."""
    assert not hasattr(core.sanitize, "fix_arabic_reversal")
    assert not hasattr(core.text_utils, "preserve_unicode_order")


def test_visible_lines_measured_in_columns_not_len() -> None:
    """25 wide glyphs occupy 50 columns, so they wrap once at width 40.

    Under len() the count is 25 // 40 == 0 and the widget reports one line.
    The console is a real pinned Console, never a mock.
    """
    widget = ToolResultWidget(
        "shell",
        "\u4f60" * 25,
        console=make_console(width=40, height=25),
    )
    widget._count_visible_lines()
    assert widget._line_count == 2, widget._line_count
