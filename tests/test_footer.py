"""Tests for the D-3b AppFooter widget (atoms replace the old Text footer)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.render import render_to_text
from ui.design.primitives import KeyValueRow, Row
from ui.widgets.footer import AppFooter


def test_render_active_is_row_of_atoms():
    """render(active=True) must be a padded Row composed of KeyValueRow atoms."""
    from rich.padding import Padding

    result = AppFooter().render(active=True)
    assert isinstance(result, Padding)
    row = result.renderable
    assert isinstance(row, Row)
    assert all(isinstance(child, KeyValueRow) for child in row.children)


def test_footer_leading_indent_uses_spacing_token():
    """The footer's leading indent must come from the GAP.footer_indent
    spacing token, not ad-hoc padding."""
    from ui.design.tokens import GAP

    result = AppFooter().render(active=True)
    assert result.left == GAP.footer_indent  # leading edge


def test_render_active_contains_jk():
    """render(active=True) must contain 'j/k' and the 'Navigate' label."""
    text = render_to_text(AppFooter().render(active=True))
    assert "j/k" in text
    assert "Navigate" in text


def test_render_active_contains_enter():
    """render(active=True) must contain the 'Expand' binding."""
    text = render_to_text(AppFooter().render(active=True))
    assert "Enter" in text
    assert "Expand" in text


def test_render_active_contains_esc():
    """render(active=True) must contain the 'Exit' binding."""
    text = render_to_text(AppFooter().render(active=True))
    assert "Esc" in text
    assert "Exit" in text


def test_render_inactive_shows_idle_hints():
    """render(active=False) must show idle hints.

    Behavior change vs NavigationFooter: the old contract rendered an
    empty string when inactive; the new contract always renders the
    [shift+tab] Input / Help hint row (declared in the D-3b commit body).
    """
    text = render_to_text(AppFooter().render(active=False))
    assert "Input" in text
    assert "[shift+tab]" in text
    assert "shortcuts" in text


def test_no_hardcoded_colors_in_footer():
    """footer.py must not contain hardcoded color strings."""
    import inspect

    import ui.widgets.footer as footer_mod

    source = inspect.getsource(footer_mod)
    forbidden = ["#000000", "#ffffff", "grey50", "bright_cyan", "red", "green"]
    for color in forbidden:
        assert color not in source, (
            f"Hardcoded color '{color}' found in footer.py source"
        )


def test_footer_uses_semantic_colors():
    """Footer colors must resolve through SEMANTIC via KeyValueRow styling."""
    from ui.design.theme.semantic import SEMANTIC

    text = render_to_text(AppFooter().render(active=True))
    for color in (SEMANTIC.text, SEMANTIC.text_dim):
        r, g, b = color.rgb
        assert f"38;2;{r};{g};{b}" in text, f"SEMANTIC {color.hex} missing"


if __name__ == "__main__":
    test_render_active_is_row_of_atoms()
    test_footer_leading_indent_uses_spacing_token()
    test_render_active_contains_jk()
    test_render_active_contains_enter()
    test_render_active_contains_esc()
    test_render_inactive_shows_idle_hints()
    test_no_hardcoded_colors_in_footer()
    test_footer_uses_semantic_colors()
    print("All footer tests passed.")
