"""D-1 Divider: a semantic separator (native Rich renderable)."""
from __future__ import annotations

from rich.console import group
from rich.rule import Rule

from ui.design.theme.color import Color
from ui.design.theme.semantic import SEMANTIC


class Divider:
    """A horizontal rule whose style resolves through SEMANTIC.border."""

    def __init__(self, color: Color | None = None):
        self.color = color or SEMANTIC.border

    def __rich_console__(self, console, options):
        yield Rule(style=self.color.to_rich_style())
