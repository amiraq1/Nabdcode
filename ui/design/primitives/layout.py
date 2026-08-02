"""D-1 Row / Column: pure stateless layout combinators (native Rich renderables).

Stateless — no color, no logic, no width math. Row composes a rich Columns
(gutter from GAP), Column composes a rich Group (vertical stack).
"""
from __future__ import annotations

from rich.columns import Columns
from rich.console import Group

from ui.design.tokens import GAP


def _children(value) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


class Row:
    """Horizontal arrangement (Rich Columns under the hood; gutter = GAP.status)."""

    def __init__(self, *children):
        self.children = _children(children)

    def __rich_console__(self, console, options):
        yield Columns(self.children, padding=(0, GAP.status))


class Column:
    """Vertical arrangement (Rich Group)."""

    def __init__(self, *children):
        self.children = _children(children)

    def __rich_console__(self, console, options):
        yield Group(*self.children)
