"""Acceptance tests for NO_COLOR / accessibility fallback.

Stage 7 (UI plan): when ``NO_COLOR`` is set (or ``TERM=dumb``), every
rendering path must produce plain, readable text with NO ANSI escape
codes, while remaining semantically equivalent.
"""

from __future__ import annotations

import io
import os
import sys

import pytest
from rich.console import Console

from ui.design.theme import colors_enabled


# ── colors_enabled gate ────────────────────────────────────────────────────

def test_colors_enabled_false_when_no_color_set(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert colors_enabled(force_terminal=True) is False


def test_colors_enabled_false_when_no_color_any_value(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "yes")
    assert colors_enabled(force_terminal=True) is False


def test_colors_enabled_false_when_term_dumb(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert colors_enabled(force_terminal=True) is False


def test_colors_enabled_true_without_restrictions(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert colors_enabled(force_terminal=True) is True


def test_colors_enabled_ignores_stdout_tty(monkeypatch):
    """The gate is env-driven only (NO_COLOR / TERM), not TTY-dependent."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    # Even with captured stdout (non-TTY), colors remain enabled by default.
    assert colors_enabled() is True


# ── NO_COLOR rendering produces no ANSI ────────────────────────────────────

def test_renderer_plain_text_with_no_color(monkeypatch):
    """Renderer tool headers must carry no raw ANSI when NO_COLOR is set."""
    from engine.renderer import Renderer
    monkeypatch.setenv("NO_COLOR", "1")
    r = Renderer()
    r.tool_start("file_system", {"action": "read", "path": "core/x.py"})
    lines = r._lines
    assert lines, "Renderer produced no lines"
    for line in lines:
        assert "\x1b[" not in line, f"ANSI leaked: {line!r}"


def test_live_thought_badge_plain_text_with_no_color(monkeypatch):
    """render_bento_badge must not emit ANSI when NO_COLOR is set."""
    from ui.live_thought import render_bento_badge
    monkeypatch.setenv("NO_COLOR", "1")
    out = render_bento_badge("todos", "evidence", ansi=True)
    assert "\x1b[" not in out
    assert "TODOS" in out  # still readable


def test_console_no_color_output_has_no_escape_codes(monkeypatch):
    """A Rich Console built with color_system=None emits no ANSI."""
    monkeypatch.setenv("NO_COLOR", "1")
    buf = io.StringIO()
    c = Console(file=buf, width=200, height=24, force_terminal=False, color_system=None)
    c.print("[bold red]error[/bold red] — [yellow]retry[/yellow]")
    out = buf.getvalue()
    assert "\x1b[" not in out
    assert "error" in out
    assert "retry" in out


# ── Semantically equivalent: content preserved without color ───────────────

def test_plain_text_is_semantically_equivalent(monkeypatch):
    """The plain-text fallback must keep all content (no color-only info)."""
    monkeypatch.setenv("NO_COLOR", "1")
    buf = io.StringIO()
    c = Console(file=buf, width=200, height=24, force_terminal=False, color_system=None)
    c.print("[bold red]✖ ERROR:[/bold red] [red]engine failed[/red] — [yellow]retry[/yellow]")
    out = buf.getvalue()
    assert "✖ ERROR: engine failed" in out
    assert "retry" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
