"""D-3c.3 Gutter: fixed-width list gutter (native Rich renderable).

Keeps the status column stable across all four (selected x collapsed)
header combinations: each slot renders its glyph or a same-width blank
when inactive. The width is owned ONCE by the GUTTER token; slot widths
are the wcwidth of the glyph each slot holds, so an inactive slot is a
blank of exactly the glyph's width and the status icon never shifts.

Resolves glyphs exclusively through Icon and colors through SEMANTIC
(no glyph literals, no hex values, no rich Style construction).
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from ui.design.icons import Icon
from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import GUTTER


class Gutter:
    """Two fixed slots: selection (glyph or blank) then collapse (glyph or blank).

    Native Rich renderable: renders exactly ONE Text of GUTTER.width cells
    so it composes as a single measured child inside Row (Row pads children
    with GAP.status, so two separate Texts would gain an extra gap between
    the slots and break the fixed width).
    """

    def __init__(self, *, selected: bool = False, collapsed: bool = False) -> None:
        self.selected = selected
        self.collapsed = collapsed

    def _line(self) -> Text:
        """One Text of GUTTER.width cells — glyph or same-width blank per slot."""
        line = Text()
        if self.selected:
            line.append(Icon.glyph(Icon.SELECT), style=SEMANTIC.selection.to_rich_style())
        else:
            line.append(" " * GUTTER.selection_slot)
        if self.collapsed:
            line.append(Icon.glyph(Icon.COLLAPSE), style=SEMANTIC.text_muted.to_rich_style())
        else:
            line.append(" " * GUTTER.collapse_slot)
        return line

    def __rich_console__(self, console, options) -> RenderableType:
        yield self._line()

    def __rich_measure__(self, console, options):
        """Faithful width (GUTTER.width) so Gutter composes inside Row."""
        from rich.measure import Measurement
        return Measurement.get(console, options, self._line())
