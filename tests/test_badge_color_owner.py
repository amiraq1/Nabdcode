"""Badge color ownership guards for Rich and ANSI render paths."""
from __future__ import annotations

from pathlib import Path

from rich.text import Text

from tests.support.render import render_to_text
from ui.design.theme.semantic import SEMANTIC
from ui.live_thought import render_bento_badge


# The literal action color may live ONLY in the files listed here.
# If the token definition layer moves, this guard will fail. That
# failure IS the notification: update this tuple deliberately.
# Never bypass it by loosening the search.
_PERMITTED_OWNERS = ("ui/design/theme/semantic.py",)


def test_no_literal_action_color_outside_its_owner():
    """Raw action color literals are confined to the semantic owner."""
    root = Path(__file__).resolve().parents[1]
    matches = []
    for base in (root / "ui", root / "engine"):
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            if relative in _PERMITTED_OWNERS:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "#0891b2" in line.lower():
                    matches.append(f"{relative}:{lineno}: {line.strip()}")
    assert not matches, "literal action color outside its owner:\n" + "\n".join(matches)


def test_badge_color_has_a_single_owner():
    """Rich and ANSI action badges resolve the same semantic RGB color."""
    rich = render_to_text(Text("TODOS", style=f"bold white on {SEMANTIC.action_badge}"))
    ansi = render_bento_badge("todos", "evidence")
    expected = "48;2;8;145;178"
    assert SEMANTIC.action_badge.rgb == (8, 145, 178)
    assert expected in rich
    assert expected in ansi
    assert " DEFAULT " not in ansi
