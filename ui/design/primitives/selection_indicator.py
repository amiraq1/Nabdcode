"""D-1 SelectionIndicator: selection affordance glyph (native Rich renderable).

Resolves the selection cursor exclusively through Icon (no glyph literals)
and SEMANTIC (no color literals). Composes inside Row/Column like every
other atom -- Rich owns measurement via __rich_measure__.
"""
from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from ui.design.icons import Icon
from ui.design.theme.semantic import SEMANTIC


class SelectionIndicator:
    """Selection cursor: renders the selection glyph with SEMANTIC.selection.

    Native Rich renderable. Color flows from SEMANTIC; no hex values,
    no rich style constructor calls, no glyph literal.
    """

    def __init__(self) -> None:
        self.icon = Icon.SELECT

    def _line(self) -> Text:
        line = Text()
        line.append(Icon.glyph(self.icon), style=SEMANTIC.selection.to_rich_style())
        return line

    def __rich_console__(self, console, options) -> RenderableType:
        yield self._line()

    def __rich_measure__(self, console, options):
        """Faithful width so SelectionIndicator composes inside Row."""
        from rich.measure import Measurement
        return Measurement.get(console, options, self._line())
