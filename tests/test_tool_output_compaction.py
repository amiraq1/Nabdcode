"""Acceptance tests for tool output compaction.

Stage 5 (UI plan): tool output must collapse at a consistent 5-line
threshold in BOTH rendering paths (REPL via ``collapse_lines`` and
one-shot via ``Renderer.tool_end``), with the same footer text
``... +N lines [ctrl+o to expand]``.  Full output must remain
recoverable via expand.
"""

from __future__ import annotations

import io
import pytest
from rich.console import Console

from engine.renderer import Renderer
from ui.cc_style import collapse_lines


# ── collapse_lines (REPL path) ─────────────────────────────────────────────

def test_collapse_lines_default_threshold_is_five():
    lines = [f"line {i}" for i in range(8)]
    out = collapse_lines(lines)
    assert len(out) == 6  # 5 kept + 1 footer
    assert out[:5] == [f"line {i}" for i in range(5)]
    assert out[5] == "... +3 lines [ctrl+o to expand]"


def test_collapse_lines_under_five_keeps_all():
    lines = [f"line {i}" for i in range(4)]
    assert collapse_lines(lines) == lines


def test_collapse_lines_exactly_five_keeps_all():
    lines = [f"line {i}" for i in range(5)]
    assert collapse_lines(lines) == lines


def test_collapse_lines_footer_has_ctrl_o_hint():
    out = collapse_lines(["a"] * 7)
    assert "ctrl+o to expand" in out[-1]


# ── Renderer.tool_end (one-shot path) ──────────────────────────────────────

def test_renderer_collapses_at_five_lines():
    r = Renderer()
    r.tool_end("execute_shell", success=True,
               output="\n".join(f"out{i}" for i in range(9)))
    lines = r._lines
    # Secondary line ("9 lines") + 5 shown + footer
    shown = [l for l in lines if "out" in l]
    assert len(shown) == 5, f"Expected 5 shown lines, got {len(shown)}: {lines}"
    footer = [l for l in lines if "ctrl+o to expand" in l]
    assert len(footer) == 1
    assert "+4 lines" in footer[0]


def test_renderer_under_five_shows_all():
    r = Renderer()
    r.tool_end("execute_shell", success=True, output="a\nb\nc")
    lines = r._lines
    # The output lines are wrapped in ANSI (dim + tree prefix); strip them
    # and check the plain content is present.
    import re
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in lines]
    assert any(x.strip().endswith(("a", "b", "c")) for x in plain)


def test_renderer_full_output_recoverable_via_expand():
    r = Renderer()
    full = "\n".join(f"out{i}" for i in range(12))
    r.tool_end("execute_shell", success=True, output=full)
    expanded = r.expand_last()
    assert expanded is not None
    for i in range(12):
        assert f"out{i}" in expanded


# ── Both paths use the same threshold and footer ───────────────────────────

def test_renderer_and_collapse_lines_agree_on_threshold():
    """Both paths must collapse 6 lines the same way."""
    lines6 = [f"l{i}" for i in range(6)]
    out = collapse_lines(lines6)
    assert out[-1] == "... +1 lines [ctrl+o to expand]"

    r = Renderer()
    r.tool_end("execute_shell", success=True, output="\n".join(lines6))
    r_lines = r._lines
    assert any("ctrl+o to expand" in l for l in r_lines)


def test_console_renders_footer_without_ansi_breakage():
    """The footer text must render cleanly through Rich."""
    from rich.text import Text
    buf = io.StringIO()
    c = Console(file=buf, width=200, height=24, force_terminal=False, color_system=None)
    c.print(Text.from_ansi(collapse_lines(["a"] * 7)[-1]))
    out = buf.getvalue()
    assert "+2 lines" in out
    assert "[ctrl+o to expand]" in out
    assert "\x1b[" not in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
