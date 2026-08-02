"""Tests for the D-3b AppHeader widget (logo + session metadata via atoms)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.render import render_to_text
from ui.design.primitives import Column
from ui.widgets.header import AppHeader


def test_header_is_column_of_centered_parts():
    """render() must be a Column: centered logo + centered status row."""
    result = AppHeader(workspace="w", model="m").render()
    assert isinstance(result, Column)
    assert len(result.children) == 2


def test_header_shows_session_metadata():
    """render() must show status badge, model and workspace."""
    text = render_to_text(AppHeader(workspace="smart-agent", model="test-model").render())
    assert "System Ready" in text
    assert "test-model" in text
    assert "smart-agent" in text


def test_header_defaults_workspace_to_cwd():
    """AppHeader() must default workspace to the basename of the cwd."""
    import os

    header = AppHeader()
    assert header.workspace == os.path.basename(os.getcwd())


def test_header_uses_semantic_colors():
    """Header colors must resolve through SEMANTIC (logo + atoms)."""
    from ui.design.theme.semantic import SEMANTIC

    text = render_to_text(AppHeader(workspace="w", model="m").render())
    for color in (SEMANTIC.text, SEMANTIC.text_dim, SEMANTIC.success):
        r, g, b = color.rgb
        assert f"38;2;{r};{g};{b}" in text, f"SEMANTIC {color.hex} missing"


def test_header_carries_no_color_literals():
    """header.py must carry no hex literals and no rich color names."""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "widgets" / "header.py").read_text()
    assert not re.findall(r"#[0-9a-fA-F]{3,8}", src), "hex literals in header.py"
    names = re.findall(
        r"\b(?:cyan|magenta|violet|green|red|yellow|blue|white|black|"
        r"grey|gray|bright_[a-z]+)\b",
        src, re.IGNORECASE,
    )
    assert not names, f"rich color names in header.py: {names}"


if __name__ == "__main__":
    test_header_is_column_of_centered_parts()
    test_header_shows_session_metadata()
    test_header_defaults_workspace_to_cwd()
    test_header_uses_semantic_colors()
    test_header_carries_no_color_literals()
    print("All header tests passed.")
