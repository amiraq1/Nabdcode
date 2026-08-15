"""tests/test_cc_style_renderer.py — UI-CC-1: Claude-Code-style rendering primitives.

Red-guard tests for ``ui/cc_style.py`` (pure functions).
"""

from __future__ import annotations

import pytest

from ui.cc_style import (
    badge_for_tool,
    collapse_lines,
    diff_pairs,
    todo_line,
    format_tokens,
    next_status_verb,
)


# ── ع1: badge_for_tool_maps_correctly ────────────────────────────────────────

def test_badge_for_tool_maps_correctly() -> None:
    assert badge_for_tool("file_system.read")[0] == "READ"
    assert badge_for_tool("execute_shell")[0] == "SHELL"
    assert badge_for_tool("file_system.write")[0] == "EDIT"
    assert badge_for_tool("web_search")[0] == "SEARCH"
    # list_dir is not a registered tool → falls back to uppercase-truncated name
    assert badge_for_tool("list_dir")[0] == "LIST_DIR"


# ── ع2: collapse_lines_shows_footer ──────────────────────────────────────────

def test_collapse_lines_shows_footer() -> None:
    lines = [f"line {i}" for i in range(12)]
    out = collapse_lines(lines, keep=3)
    assert len(out) == 4
    assert out[:3] == ["line 0", "line 1", "line 2"]
    assert "+9 lines" in out[3] and "ctrl+o" in out[3]


def test_collapse_lines_short_passthrough() -> None:
    lines = ["a", "b", "c"]
    assert collapse_lines(lines, keep=3) == lines


# ── ع3: diff_pairs_signs_correct ─────────────────────────────────────────────

def test_diff_pairs_signs_correct() -> None:
    pairs = diff_pairs(["a", "b"], ["a", "c"])
    signs = [s for s, _ in pairs]
    assert signs == ["=", "-", "+"]
    texts = [t for _, t in pairs]
    assert texts == ["a", "b", "c"]


# ── ع4: todos_strikethrough_completed ────────────────────────────────────────

def test_todos_strikethrough_completed() -> None:
    _, style_done = todo_line("done item", done=True)
    assert "strike" in style_done
    _, style_pending = todo_line("pending item", done=False)
    assert "strike" not in style_pending


# ── ع5: format_tokens_human_readable ─────────────────────────────────────────

def test_format_tokens_human_readable() -> None:
    assert format_tokens(56700) == "56.7k"
    assert format_tokens(900) == "900"
    assert format_tokens(12345) == "12.3k"


# ── ع6: status_verb_from_known_set ───────────────────────────────────────────

def test_status_verb_from_known_set() -> None:
    known = {
        "Examining", "Editing", "Executing", "Searching",
        "Delegating", "Reasoning", "Writing",
    }
    for _ in range(10):
        assert next_status_verb() in known
