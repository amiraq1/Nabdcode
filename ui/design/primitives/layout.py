"""D-1 Row / Column: pure stateless layout combinators (native Rich renderables).

Stateless — no color, no logic, no width math. Row composes a rich Columns
(gutter from GAP); with *separator* it interleaves the given Separator token
between groups so adjacent groups are never distinguishable by whitespace
alone. Column composes a rich Group (vertical stack).
"""
from __future__ import annotations

from typing import Optional

from rich.columns import Columns
from rich.console import Group
from rich.text import Text

from ui.design.tokens import GAP, Separator


def _children(value) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


class Row:
    """Horizontal arrangement (Rich Columns under the hood; gutter = GAP.status)."""

    def __init__(self, *children, separator: Optional[Separator] = None):
        self.children = _children(children)
        self.separator = separator

    def __rich_console__(self, console, options):
        if self.separator is None:
            yield Columns(self.children, padding=(0, GAP.status))
            return
        parts: list = []
        for i, child in enumerate(self.children):
            if i:
                parts.append(Text(self.separator.glyph,
                                  style=self.separator.color.to_rich_style()))
            parts.append(child)
        yield Columns(parts, padding=(0, GAP.status))


class Column:
    """Vertical arrangement (Rich Group)."""

    def __init__(self, *children):
        self.children = _children(children)

    def __rich_console__(self, console, options):
        yield Group(*self.children)
