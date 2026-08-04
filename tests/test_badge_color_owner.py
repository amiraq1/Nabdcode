"""Badge color ownership guards for Rich and ANSI render paths."""
from __future__ import annotations

from rich.text import Text

from tests.support.render import render_to_text
from ui.design.theme.semantic import SEMANTIC
from ui.live_thought import render_bento_badge


def test_badge_color_has_a_single_owner():
    """Rich and ANSI action badges resolve the same semantic RGB color."""
    rich = render_to_text(Text("TODOS", style=f"bold white on {SEMANTIC.action_badge}"))
    ansi = render_bento_badge("todos", "evidence")
    expected = "48;2;8;145;178"
    assert SEMANTIC.action_badge.rgb == (8, 145, 178)
    assert expected in rich
    assert expected in ansi
    assert " DEFAULT " not in ansi
