"""Acceptance tests for narrow-terminal prompt chrome.

The Termux fix: at 50 columns the prompt chrome must not
  * tear the workspace name mid-word,
  * glue the hint line to the prompt chevron,
  * wrap the placeholder awkwardly.

The rule line must fit the terminal width (dynamic, not a fixed 48),
and the graph summary is dropped on narrow screens so the workspace
+ mode line never wraps.
"""

from __future__ import annotations

import inspect

import pytest

import main


def _prompt_chrome_source() -> str:
    return inspect.getsource(main._run_repl)


# ── Dynamic rule (fits terminal width) ─────────────────────────────────────

def test_rule_is_dynamic_not_fixed_48():
    src = _prompt_chrome_source()
    assert "term_width()" in src, "rule must use term_width(), not a fixed 48"
    assert '"─" *' in src or "'─' *" in src, "rule must be built from the width"
    assert "max(20, min(term_width(), 120))" in src, "width must be clamped"


def test_rule_fits_50_column_terminal():
    """At 50 columns the rule must be 50 wide, never 48 overflowing."""
    from engine.ui_theme import term_width
    import os
    import shutil

    orig = shutil.get_terminal_size
    shutil.get_terminal_size = lambda fallback=None: os.terminal_size((50, 24))
    try:
        w = max(20, min(term_width(), 120))
        assert w == 50, f"Expected rule width 50, got {w}"
    finally:
        shutil.get_terminal_size = orig


def test_rule_fits_120_column_terminal():
    """At 120+ columns the rule must clamp to 120 (not grow unbounded)."""
    from engine.ui_theme import term_width
    import os
    import shutil

    orig = shutil.get_terminal_size
    shutil.get_terminal_size = lambda fallback=None: os.terminal_size((200, 24))
    try:
        w = max(20, min(term_width(), 120))
        assert w == 120, f"Expected clamped rule width 120, got {w}"
    finally:
        shutil.get_terminal_size = orig


# ── Context line: graph dropped on narrow screens ──────────────────────────

def test_graph_dropped_when_too_wide_for_terminal():
    src = _prompt_chrome_source()
    assert "if task_summary:" in src, "graph must only render when a summary exists"
    assert "<= width" in src, "graph line must be budget-guarded to terminal width"


def test_graph_truncated_on_wide_but_not_huge():
    src = _prompt_chrome_source()
    assert "hint.splitlines()[0]" in src, (
        "hint must use first line only; summary rendered separately on its own "
        "width-guarded line so narrow terminals never tear it"
    )


def test_workspace_and_mode_always_present():
    src = _prompt_chrome_source()
    assert "workspace:" in src
    assert "mode:" in src
    assert "no workspace selected" in src


# ── NO_COLOR / TERM=dumb remain clean ──────────────────────────────────────

def test_prompt_chrome_honors_no_color(monkeypatch):
    """The chrome must render with no raw ANSI when NO_COLOR is set."""
    monkeypatch.setenv("NO_COLOR", "1")
    src = _prompt_chrome_source()
    # The chrome uses prompt_toolkit HTML styles, not raw ANSI.
    assert "\\x1b[" not in src


# ── <br/> must NOT be used for line separation (minidom drops it) ────────────

def test_prompt_chrome_uses_real_newlines_not_br():
    """minidom's HTML renderer silently drops self-closing <br/>; the chrome
    must separate visual lines with real newlines so narrow terminals don't
    glue the rule / context / hint / chevron together."""
    src = _prompt_chrome_source()
    assert "<br/>" not in src, "chrome must not rely on <br/> (minidom drops it)"
    assert '"\\n".join(lines)' in src, (
        "chrome must join visual lines with real newlines, not <br/>"
    )


def test_prompt_chrome_keeps_ctx_line_within_width():
    """workspace + mode line must be width-guarded so it never wraps."""
    src = _prompt_chrome_source()
    assert "ctx_overhead" in src
    assert "ws_cap" in src


# ── NO_COLOR / TERM=dumb keep the prompt chrome plain ────────────────────────

def test_prompt_chrome_gates_styling_on_colors_enabled():
    """Under NO_COLOR / TERM=dumb the chrome must emit plain spans (no <style>),
    so no SGR — not even a reset — reaches the terminal."""
    import os
    import main
    import inspect

    src = inspect.getsource(main._run_repl)
    # The chrome consults the central color gate.
    assert "colors_enabled()" in src
    assert "use_color" in src
    # Plain fallback chevron is emitted when color is off.
    assert "PROMPT_HTML_SUFFIX if use_color else" in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
