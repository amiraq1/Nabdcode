"""Tests for the collapsible ToolResultWidget."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ui.widgets.tool_result import ToolResultWidget
from ui.theme import CUSTOM_THEME
from ui.design.icons import Icon
from tests.support.render import render_to_text, strip_ansi


# ── Helpers ──────────────────────────────────────────────────────────────────

def _render_to_string(widget: ToolResultWidget) -> str:
    """Render the widget to a plain string for assertions."""
    return render_to_text(widget.render(), width=120, height=25, theme=CUSTOM_THEME)


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
    """Failure should show the canonical error glyph (Icon.ERROR, ✖) in the
    collapsed header. D-2: the old ballot-x (✗, Icon.DELETE) is replaced by
    the registry's error icon."""
    output = "\n".join(f"line {i}" for i in range(10))
    w = ToolResultWidget("shell", output, success=False)
    rendered = _render_to_string(w)
    assert Icon.glyph(Icon.ERROR) in rendered


def test_success_shows_green_check():
    w = ToolResultWidget("read", "content here", success=True)
    rendered = _render_to_string(w)
    assert "✓" in rendered


# ── Badge rendering ──────────────────────────────────────────────────────────

def test_badge_resolves_semantic_color():
    """Badge color must resolve via Badge meaning -> SEMANTIC, not a
    hardcoded palette (ACTION_COLORS is superseded by the D-1 atoms)."""
    from ui.design.primitives import Badge
    from ui.design.theme.semantic import SEMANTIC

    w = ToolResultWidget("shell", "ls output")
    label = w._get_badge()
    meaning = w._badge_meaning()
    assert label == "SHELL"          # label vocabulary unchanged
    assert meaning == "info"
    assert Badge(label, meaning).meaning == meaning

    colored = render_to_text(w.render(), width=80, height=25)
    r, g, b = SEMANTIC.info.rgb
    assert f"38;2;{r};{g};{b}" in colored


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
    """Expanded view truncates output > 2000 chars. V-07a contract: long
    visual lines now collapse by default, so force expanded to test the
    truncation path directly (collapse is asserted in the next test)."""
    output = "x" * 3000
    w = ToolResultWidget("shell", output)
    w._collapsed = False          # V-07a: force expanded; collapse tested below
    rendered = _render_to_string(w)
    assert "truncated" in rendered
    assert len(rendered) < 4000  # not the full 3000 chars


def test_long_single_line_collapses_by_visual_length():
    """V-07a NEW contract: a single very long line counts as many visual
    lines and collapses by default (this is the intended improvement)."""
    output = "x" * 3000
    w = ToolResultWidget("shell", output)
    w.render()                    # triggers _count_visible_lines
    assert w.line_count > 5
    assert w.is_collapsed


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_no_content_output():
    """Output that is only whitespace should be treated as empty."""
    w = ToolResultWidget("shell", "   \n  \n  ")
    w._count_visible_lines()
    assert w.line_count == 0
    w._generate_preview()
    assert w.preview == ""


def test_render_returns_section_panel():
    """render() must return the D-1 container atom (SectionPanel)."""
    from ui.design.primitives import SectionPanel

    w = ToolResultWidget("read", "short output")
    result = w.render()
    assert isinstance(result, SectionPanel)


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
    from ui.design.theme.semantic import SEMANTIC

    w_unselected = ToolResultWidget("read", "short output")
    w_unselected.deselect()
    p_unselected = w_unselected.render()

    w_selected = ToolResultWidget("read", "short output")
    w_selected.select()
    p_selected = w_selected.render()

    # Border color must differ and resolve through SEMANTIC
    assert p_unselected.border_color != p_selected.border_color
    assert str(p_selected.border_color) == str(SEMANTIC.selection)


def test_selected_border_uses_selected_color_not_hardcoded():
    """Selected border must resolve through SEMANTIC.selection (not hardcoded)."""
    from ui.design.theme.semantic import SEMANTIC

    # Short output → expanded render
    w = ToolResultWidget("read", "short output")
    w.select()
    panel = w.render()
    assert str(panel.border_color) == str(SEMANTIC.selection)

    # Long output → collapsed render
    output = "\n".join(f"line {i}" for i in range(10))
    w2 = ToolResultWidget("read", output)
    w2.select()
    panel2 = w2.render()
    assert str(panel2.border_color) == str(SEMANTIC.selection)


def test_unselected_uses_default_border():
    """Unselected widgets must not use the selection border."""
    from ui.design.theme.semantic import SEMANTIC

    w = ToolResultWidget("read", "short output")
    panel = w.render()
    assert str(panel.border_color) != str(SEMANTIC.selection)


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

def test_error_reason_is_not_output_line_one():
    """An error whose first output line is arbitrary text (e.g. 'out 0') must NOT surface that text as the reason."""
    w = ToolResultWidget("shell", "out 0\narbitrary output", success=False)
    rendered = _render_to_string(w)
    assert "reason" not in rendered
    assert "out 0" in rendered

def test_error_without_reason_omits_segment():
    """Skeleton equality must still hold with the segment absent — SUCCESS and reasonless-ERROR share the skeleton."""
    import re
    from ui.design.icons import Icon
    
    ok = ToolResultWidget("shell", "out 0", success=True)
    err = ToolResultWidget("shell", "out 0", success=False)
    
    def norm(s: str) -> str:
        s = (s.replace(Icon.glyph(Icon.SUCCESS), "O")
              .replace(Icon.glyph(Icon.ERROR), "O")
              .replace("ok", "V")
              .replace("error", "V"))
        return re.sub(r" +", " ", s).strip()
        
    a, b = _render_to_string(ok), _render_to_string(err)
    assert norm(strip_ansi(a)) == norm(strip_ansi(b))
