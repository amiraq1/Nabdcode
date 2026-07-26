"""Tests for Phase 4 navigation footer help widget."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import RenderableType
from rich.text import Text

from ui.widgets.footer import NavigationFooter
from ui.theme import FOOTER_COLOR


def test_render_active_is_renderable():
    """render(active=True) must return a Rich renderable."""
    footer = NavigationFooter()
    result = footer.render(active=True)
    assert isinstance(result, RenderableType) or hasattr(result, "__rich__")


def test_render_active_contains_jk():
    """render(active=True) must contain 'j/k'."""
    footer = NavigationFooter()
    result = footer.render(active=True)
    # Text objects expose .plain for the raw string
    plain = result.plain if hasattr(result, "plain") else str(result)
    assert "j/k" in plain


def test_render_active_contains_enter():
    """render(active=True) must contain 'Enter'."""
    footer = NavigationFooter()
    result = footer.render(active=True)
    plain = result.plain if hasattr(result, "plain") else str(result)
    assert "Enter" in plain


def test_render_active_contains_esc():
    """render(active=True) must contain 'Esc'."""
    footer = NavigationFooter()
    result = footer.render(active=True)
    plain = result.plain if hasattr(result, "plain") else str(result)
    assert "Esc" in plain


def test_render_inactive_empty():
    """render(active=False) must render empty."""
    footer = NavigationFooter()
    result = footer.render(active=False)
    plain = result.plain if hasattr(result, "plain") else str(result)
    assert plain == ""


def test_no_hardcoded_colors_in_footer():
    """footer.py must not contain hardcoded color strings."""
    import ui.widgets.footer as footer_mod
    import inspect

    source = inspect.getsource(footer_mod)
    # Strip the import line that references FOOTER_COLOR
    lines = [
        line for line in source.splitlines()
        if "FOOTER_COLOR" not in line
    ]
    source_without_import = "\n".join(lines)
    # No inline hex colors or named color strings should appear
    forbidden = ["#000000", "#ffffff", "grey50", "bright_cyan", "red", "green"]
    for color in forbidden:
        assert color not in source_without_import, (
            f"Hardcoded color '{color}' found in footer.py source"
        )


def test_footer_uses_theme_color():
    """The footer text must use the FOOTER_COLOR from the theme."""
    footer = NavigationFooter()
    result = footer.render(active=True)
    assert result.style == FOOTER_COLOR


if __name__ == "__main__":
    test_render_active_is_renderable()
    test_render_active_contains_jk()
    test_render_active_contains_enter()
    test_render_active_contains_esc()
    test_render_inactive_empty()
    test_no_hardcoded_colors_in_footer()
    test_footer_uses_theme_color()
    print("All footer tests passed.")
