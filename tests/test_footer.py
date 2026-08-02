"""Tests for Phase D-3b AppFooter widget."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from ui.widgets.footer import AppFooter


def test_render_active_contains_jk():
    """render(active=True) must contain 'j/k ↑↓' via KeyValueRow."""
    footer = AppFooter()
    result = footer.render(active=True)
    
    console = Console(width=80, force_terminal=True, highlight=False)
    with console.capture() as cap:
        console.print(result)
    text = cap.get()
    
    assert "j/k" in text
    assert "Navigate" in text


def test_render_active_contains_enter():
    """render(active=True) must contain 'Enter' via KeyValueRow."""
    footer = AppFooter()
    result = footer.render(active=True)
    
    console = Console(width=80, force_terminal=True, highlight=False)
    with console.capture() as cap:
        console.print(result)
    text = cap.get()
    
    assert "Enter" in text
    assert "Expand" in text


def test_render_active_contains_esc():
    """render(active=True) must contain 'Esc' via KeyValueRow."""
    footer = AppFooter()
    result = footer.render(active=True)
    
    console = Console(width=80, force_terminal=True, highlight=False)
    with console.capture() as cap:
        console.print(result)
    text = cap.get()
    
    assert "Esc" in text
    assert "Exit" in text


def test_render_inactive_contains_idle_hints():
    """render(active=False) must render idle hints via KeyValueRow."""
    footer = AppFooter()
    result = footer.render(active=False)
    
    console = Console(width=80, force_terminal=True, highlight=False)
    with console.capture() as cap:
        console.print(result)
    text = cap.get()
    
    assert "[shift+tab]" in text
    assert "Input" in text
    assert "?" in text
    assert "Help" in text


def test_no_hardcoded_colors_in_footer():
    """footer.py must not contain hardcoded color strings."""
    import ui.widgets.footer as footer_mod
    import inspect

    source = inspect.getsource(footer_mod)
    # No inline hex colors or named color strings should appear
    forbidden = ["#000000", "#ffffff", "grey50", "bright_cyan", "red", "green"]
    for color in forbidden:
        assert color not in source, (
            f"Hardcoded color '{color}' found in footer.py source"
        )

if __name__ == "__main__":
    test_render_active_contains_jk()
    test_render_active_contains_enter()
    test_render_active_contains_esc()
    test_render_inactive_contains_idle_hints()
    test_no_hardcoded_colors_in_footer()
    print("All footer tests passed.")
