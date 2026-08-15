"""Acceptance tests for badge classification unification.

Stage 1 of the UI improvement plan: ``badge_for_tool`` (cc_style), 
``_tool_badge_label`` (live_thought), and ``map_tool_to_badge``
(ui_theme) must all classify the same tool consistently.

Before the fix, two functions disagreed:
- exec/bash → SHELL in map_tool_to_badge, TOOL in badge_for_tool
- todo_write → TODOS in map_tool_to_badge, TOOL in badge_for_tool
"""

from __future__ import annotations

import pytest

from engine.ui_theme import map_tool_to_badge
from ui.cc_style import badge_for_tool
from ui.live_thought import _tool_badge_label, _BENTO_COLORS


# ── Gap cases that were previously inconsistent ──────────────────────────

def test_exec_classified_as_shell_everywhere():
    assert map_tool_to_badge("exec") == "SHELL"
    assert badge_for_tool("exec")[0] == "SHELL"
    assert _tool_badge_label("exec") == "SHELL"


def test_bash_classified_as_shell_everywhere():
    assert map_tool_to_badge("bash") == "SHELL"
    assert badge_for_tool("bash")[0] == "SHELL"
    assert _tool_badge_label("bash") == "SHELL"


def test_todo_write_classified_as_todos_everywhere():
    assert map_tool_to_badge("todo_write") == "TODOS"
    assert badge_for_tool("todo_write")[0] == "TODOS"
    assert _tool_badge_label("todo_write") == "TODOS"


# ── All three functions agree for common tools ───────────────────────────

@pytest.mark.parametrize("tool_name, expected", [
    ("file_system", "READ"),
    ("execute_shell", "SHELL"),
    ("shell", "SHELL"),
    ("bash", "SHELL"),
    ("exec", "SHELL"),
    ("web_search", "SEARCH"),
    ("rag_search", "RAG"),
    ("search_memory", "SEARCH"),
    ("todo_write", "TODOS"),
    ("task", "TASK"),
    ("kill", "KILL"),
    ("code_intelligence", "CODE_INTELLI"),
    ("taste_manager", "TASTE_MANAGE"),
])
def test_three_paths_agree(tool_name, expected):
    label_1 = map_tool_to_badge(tool_name)
    label_2 = badge_for_tool(tool_name)[0]
    label_3 = _tool_badge_label(tool_name)
    assert label_1 == expected, f"map_tool_to_badge({tool_name!r}) = {label_1!r}"
    assert label_2 == expected, f"badge_for_tool({tool_name!r}) = {label_2!r}"
    assert label_3 == expected, f"_tool_badge_label({tool_name!r}) = {label_3!r}"


def test_file_system_write_is_edit_everywhere():
    """file_system with action=write must be EDIT in all three paths."""
    args = {"action": "write"}
    assert map_tool_to_badge("file_system", args) == "EDIT"
    assert badge_for_tool("file_system", args)[0] == "EDIT"
    assert _tool_badge_label("file_system", args) == "EDIT"


def test_kill_has_red_style():
    """KILL badge must have the red-on-white style, not the default badge style."""
    label, style = badge_for_tool("kill")
    assert label == "KILL"
    assert "red" in style or "err" in style


def test_non_kill_badges_use_default_style():
    """Non-KILL badges must use BADGE_STYLE (not a special color)."""
    from ui.cc_style import BADGE_STYLE
    for tool in ("file_system", "execute_shell", "web_search", "task", "todo_write"):
        label, style = badge_for_tool(tool)
        assert style == BADGE_STYLE, f"tool={tool} label={label} style={style!r}"


def test_bento_colors_cover_all_labels():
    """Every label returned by map_tool_to_badge must have a bento color entry
    or fall back to DEFAULT."""
    tools = ["file_system", "execute_shell", "shell", "exec", "bash",
             "web_search", "rag_search", "search_memory", "todo_write",
             "task", "kill", "code_intelligence", "taste_manager",
             "python_repl", "graphify"]
    for tool in tools:
        label = map_tool_to_badge(tool)
        # render_bento_badge falls back to DEFAULT for unknown labels
        fallback = _BENTO_COLORS.get(label, _BENTO_COLORS["DEFAULT"])
        assert fallback is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
