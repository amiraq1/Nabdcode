"""Regression tests for ANSI escape code leakage in terminal rendering.

Stage 0-A: The thought summary line produced by ``thought_summary()`` contains
raw ANSI escape sequences (\x1b[38;2;...m).  When this string is passed directly
to ``Console().print()`` as a plain string, Rich's markup parser:

1. Tries to interpret ``[activity summary]`` / ``[ctrl+o to expand]`` as a
   Rich markup tag (it is not a valid style → rendered as literal text).
2. Passes through the ANSI escape codes as raw bytes, which appear as
   ``^[38;2;...`` or ``\x1b[38;2;...`` in captured / non-TTY output.

The fix: the Rich REPL path must never feed raw ANSI strings to
``Console().print()``.  Either wrap with ``Text.from_ansi()`` or use the
plain-text ``thought_line`` from ``cc_style``.
"""

from __future__ import annotations

import io

from rich.console import Console
from rich.text import Text

from engine.ui_theme import thought_summary


# ── ANSI escape detection ─────────────────────────────────────────────────

_RAW_ANSI_PATTERNS = ("[38;", "[0m", "[2m", "[1m", "[48;", "\x1b[")


def _capture_rich_print(text: str) -> str:
    """Render *text* through a real Rich Console into a StringIO buffer.

    Mirrors the production call site which wraps ANSI strings in Text.from_ansi()
    before handing them to Console().print().
    """
    buf = io.StringIO()
    console = Console(file=buf, width=200, height=24, force_terminal=False, color_system=None)
    console.print(Text.from_ansi(text))
    return buf.getvalue()


# ── Stage 0: reproduce the leak ───────────────────────────────────────────

def test_thought_summary_leaks_raw_ansi_via_console_print():
    """Reproduce: ``Console().print(thought_summary(...))`` leaks ANSI codes.

    BEFORE the fix, the rendered output contains literal escape-code fragments
    like ``[38;2;`` or ``^[38;`` because Rich cannot consume raw ANSI passed as
    a plain string.
    """
    line = thought_summary(1.4, expand_hint="activity summary")
    output = _capture_rich_print(line)

    # The human-readable content must be present.
    assert "Thought for 1 second" in output

    # No raw ANSI fragments should survive in the rendered output.
    leaked = [p for p in _RAW_ANSI_PATTERNS if p in output]
    assert not leaked, (
        f"Raw ANSI leaked in thought line: {leaked}. "
        f"Output was: {output!r}"
    )


def test_thought_summary_with_ctrl_o_hint_does_not_break_rich_markup():
    """The ``[ctrl+o to expand]`` hint must not be parsed as Rich markup."""
    line = thought_summary(0.5, expand_hint="ctrl+o to expand")
    output = _capture_rich_print(line)

    assert "Thought for 0 seconds" in output
    # Must not contain literal bracket-escape artifacts.
    assert "[38;" not in output
    assert "[0m" not in output
    assert "[2m" not in output


def test_thought_line_plain_has_no_ansi():
    """``cc_style.thought_line`` must be plain text (no ANSI escapes)."""
    from ui.cc_style import thought_line

    line = thought_line(1)
    assert "\x1b[" not in line
    assert "Thought for 1 second" in line
