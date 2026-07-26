"""Tests for the collapsible ToolResultWidget."""

import os
import sys
from io import StringIO

from rich.console import Console

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ui.widgets.tool_result import ToolResultWidget
from ui.theme import CUSTOM_THEME


# ── Helpers ──────────────────────────────────────────────────────────────────

def _render_to_string(widget: ToolResultWidget) -> str:
    """Render the widget to a plain string for assertions."""
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None, theme=CUSTOM_THEME)
    widget._console = console
    console.print(widget.render())
    return buf.getvalue()


# ── Line counting ────────────────────────────────────────────────────────────

def test_line_count_counts_non_empty_lines():
    w = ToolResultWidget("read", "line1\n\nline3\n\nline5")
    w._count_visible_lines()
    assert w.line_count == 3


def test_line_count_empty_output():
    w = ToolResultWidget("shell", "")
    w._count_visible_lines()
    assert w.line_count == 0


def test_line_count_all_empty_lines():
    w = ToolResultWidget("shell", "\n\n\n")
    w._count_visible_lines()
    assert w.line_count == 0


# ── Preview generation ───────────────────────────────────────────────────────

def test_preview_first_non_empty_line_max_3_words():
    w = ToolResultWidget("read", "hello world from python\nline2\nline3")
    w._generate_preview()
    assert w.preview == "hello world from..."


def test_preview_exact_3_words_no_ellipsis():
    w = ToolResultWidget("read", "one two three\nline2")
    w._generate_preview()
    assert w.preview == "one two three"


def test_preview_fewer_than_3_words():
    w = ToolResultWidget("read", "hello world\nline2")
    w._generate_preview()
    assert w.preview == "hello world"


def test_preview_single_word():
    w = ToolResultWidget("read", "hello\nline2")
    w._generate_preview()
    assert w.preview == "hello"


def test_preview_empty_output():
    w = ToolResultWidget("shell", "")
    w._generate_preview()
    assert w.preview == ""


def test_preview_skips_leading_empty_lines():
    w = ToolResultWidget("read", "\n\nactual content here more\nline2")
    w._generate_preview()
    assert w.preview == "actual content here..."


# ── Collapse threshold ───────────────────────────────────────────────────────

def test_short_output_renders_expanded():
    """Output with <= 5 non-empty lines should render the full Panel."""
    output = "\n".join(f"line {i}" for i in range(5))
    w = ToolResultWidget("read", output)
    rendered = _render_to_string(w)
    assert "line 0" in rendered
    assert "line 4" in rendered
    assert "►" not in rendered


def test_long_output_renders_collapsed_by_default():
    """Output with > 5 non-empty lines should render collapsed."""
    output = "\n".join(f"line {i}" for i in range(10))
    w = ToolResultWidget("read", output)
    rendered = _render_to_string(w)
    assert "►" in rendered
    assert "line 9" not in rendered  # full content not shown when collapsed


def test_collapsed_shows_preview():
    """Collapsed view should show the preview (first 3 words)."""
    output = "\n".join(f"word{i} word{i} word{i} word{i}" for i in range(10))
    w = ToolResultWidget("read", output)
    rendered = _render_to_string(w)
    assert "word0 word0 word0..." in rendered


def test_collapsed_shows_line_count():
    """Collapsed header should show the non-empty line count."""
    output = "\n".join(f"line {i}" for i in range(10))
    w = ToolResultWidget("read", output)
    rendered = _render_to_string(w)
    assert "10 lines" in rendered


def test_empty_output_shows_clean():
    """Empty output should report 'clean' in the info string."""
    w = ToolResultWidget("shell", "")
    assert w._get_info() == "clean"


# ── Toggle ───────────────────────────────────────────────────────────────────

def test_toggle_switches_to_expanded():
    output = "\n".join(f"line {i}" for i in range(10))
    w = ToolResultWidget("read", output)
    assert w.is_collapsed is True
    w.toggle()
    assert w.is_collapsed is False
    rendered = _render_to_string(w)
    assert "line 0" in rendered
    assert "line 9" in rendered


def test_toggle_back_to_collapsed():
    output = "\n".join(f"line {i}" for i in range(10))
    w = ToolResultWidget("read", output)
    w.toggle()  # expanded
    w.toggle()  # back to collapsed
    assert w.is_collapsed is True
    rendered = _render_to_string(w)
    assert "►" in rendered
    assert "line 9" not in rendered


def test_toggle_short_output_still_expanded():
    """Toggling a short output should still render expanded (threshold met)."""
    output = "\n".join(f"line {i}" for i in range(3))
    w = ToolResultWidget("read", output)
    w.toggle()  # collapsed flag set, but threshold says expanded
    rendered = _render_to_string(w)
    assert "line 0" in rendered
    assert "line 2" in rendered


# ── Success / failure indicators ─────────────────────────────────────────────

def test_failure_shows_red_x():
    """Failure should show ✗ in the collapsed header."""
    output = "\n".join(f"line {i}" for i in range(10))
    w = ToolResultWidget("shell", output, success=False)
    rendered = _render_to_string(w)
    assert "✗" in rendered


def test_success_shows_green_check():
    w = ToolResultWidget("read", "content here", success=True)
    rendered = _render_to_string(w)
    assert "✓" in rendered


# ── Badge rendering ──────────────────────────────────────────────────────────

def test_badge_uses_action_colors():
    """Badge should use ACTION_COLORS, not hardcoded colors."""
    from ui.theme import ACTION_COLORS

    w = ToolResultWidget("shell", "ls output")
    badge = w._get_badge()
    color = w._get_badge_color()
    assert badge in ACTION_COLORS
    assert color == ACTION_COLORS[badge]


def test_badge_for_file_system_read():
    w = ToolResultWidget("file_system", "file content", args={"action": "read"})
    assert w._get_badge() == "READ"


def test_badge_for_file_system_write():
    w = ToolResultWidget("file_system", "written", args={"action": "write"})
    assert w._get_badge() == "EDIT"


def test_badge_for_shell():
    w = ToolResultWidget("execute_shell", "ls -la")
    assert w._get_badge() == "SHELL"


# ── Truncation ───────────────────────────────────────────────────────────────

def test_long_output_truncated_in_expanded():
    """Expanded view should truncate output > 2000 chars."""
    output = "x" * 3000
    w = ToolResultWidget("shell", output)
    rendered = _render_to_string(w)
    assert "truncated" in rendered
    assert len(rendered) < 4000  # not the full 3000 chars


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_no_content_output():
    """Output that is only whitespace should be treated as empty."""
    w = ToolResultWidget("shell", "   \n  \n  ")
    w._count_visible_lines()
    assert w.line_count == 0
    w._generate_preview()
    assert w.preview == ""


def test_render_returns_panel():
    """render() should return a Rich renderable (Panel)."""
    from rich.panel import Panel

    w = ToolResultWidget("read", "short output")
    result = w.render()
    assert isinstance(result, Panel)


def test_widget_owns_state():
    """Widget should own collapse state independently of rendering."""
    w = ToolResultWidget("read", "line1\nline2\nline3\nline4\nline5\nline6")
    assert w.is_collapsed is True
    assert w.line_count == 0  # not counted until render()
    w.render()
    assert w.line_count == 6
    assert w.is_collapsed is True


# ── Selection state (Phase 1) ────────────────────────────────────────────────

def test_default_selected_is_false():
    """selected must default to False."""
    w = ToolResultWidget("read", "short output")
    assert w.selected is False


def test_select_sets_selected_true():
    """select() must set selected to True."""
    w = ToolResultWidget("read", "short output")
    w.select()
    assert w.selected is True


def test_deselect_sets_selected_false():
    """deselect() must set selected to False."""
    w = ToolResultWidget("read", "short output")
    w.select()
    w.deselect()
    assert w.selected is False


def test_select_deselect_chaining():
    """select().deselect() must leave selected == False (chaining safe)."""
    w = ToolResultWidget("read", "short output")
    w.select().deselect()
    assert w.selected is False


def test_render_differs_when_selected():
    """render() output must differ between selected=True and selected=False."""
    from ui.theme import SELECTED_COLOR

    w_unselected = ToolResultWidget("read", "short output")
    w_unselected.deselect()
    p_unselected = w_unselected.render()

    w_selected = ToolResultWidget("read", "short output")
    w_selected.select()
    p_selected = w_selected.render()

    # Border style must differ
    assert p_unselected.border_style != p_selected.border_style
    # Selected panel must use SELECTED_COLOR
    assert str(p_selected.border_style) == SELECTED_COLOR


def test_selected_border_uses_selected_color_not_hardcoded():
    """Selected border must use SELECTED_COLOR from theme (not hardcoded)."""
    from ui.theme import SELECTED_COLOR

    # Short output → expanded render
    w = ToolResultWidget("read", "short output")
    w.select()
    panel = w.render()
    assert str(panel.border_style) == SELECTED_COLOR

    # Long output → collapsed render
    output = "\n".join(f"line {i}" for i in range(10))
    w2 = ToolResultWidget("read", output)
    w2.select()
    panel2 = w2.render()
    assert str(panel2.border_style) == SELECTED_COLOR


def test_unselected_uses_default_border():
    """Unselected widgets must use the default border (not SELECTED_COLOR)."""
    from ui.theme import SELECTED_COLOR

    w = ToolResultWidget("read", "short output")
    panel = w.render()
    assert str(panel.border_style) != SELECTED_COLOR


if __name__ == "__main__":
    test_line_count_counts_non_empty_lines()
    test_line_count_empty_output()
    test_line_count_all_empty_lines()
    test_preview_first_non_empty_line_max_3_words()
    test_preview_exact_3_words_no_ellipsis()
    test_preview_fewer_than_3_words()
    test_preview_single_word()
    test_preview_empty_output()
    test_preview_skips_leading_empty_lines()
    test_short_output_renders_expanded()
    test_long_output_renders_collapsed_by_default()
    test_collapsed_shows_preview()
    test_collapsed_shows_line_count()
    test_empty_output_shows_clean()
    test_toggle_switches_to_expanded()
    test_toggle_back_to_collapsed()
    test_toggle_short_output_still_expanded()
    test_failure_shows_red_x()
    test_success_shows_green_check()
    test_badge_uses_action_colors()
    test_badge_for_file_system_read()
    test_badge_for_file_system_write()
    test_badge_for_shell()
    test_long_output_truncated_in_expanded()
    test_no_content_output()
    test_render_returns_panel()
    test_widget_owns_state()
    test_default_selected_is_false()
    test_select_sets_selected_true()
    test_deselect_sets_selected_false()
    test_select_deselect_chaining()
    test_render_differs_when_selected()
    test_selected_border_uses_selected_color_not_hardcoded()
    test_unselected_uses_default_border()
    print("All ToolResultWidget tests passed.")
