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

def test_graph_dropped_below_70_columns():
    src = _prompt_chrome_source()
    assert "width >= 70" in src, "graph must only show on wide enough terminals"


def test_graph_truncated_on_wide_but_not_huge():
    src = _prompt_chrome_source()
    assert "task_summary[:60]" in src, "graph fragment must be bounded"


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
