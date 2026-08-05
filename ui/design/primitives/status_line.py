"""D-1 StatusLine: ONE component, FIVE personalities (native Rich renderable).

Composes via __rich_console__ so it can live directly inside Group / Panel /
Columns / Table. Colors flow from PersonalityStyle.color via to_rich_style();
the personality weight is merged as a style *string* (no explicit rich Style
object is constructed in this layer). No manual width math — Rich measures.
"""
from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from ui.design.icons import Icon
from ui.design.state import UIState, UI_STATES
from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import GAP

from ui.design.primitives.personality import (
    PersonalityStyle, style_of, to_style_str,
)


class StatusLine:
    """Single status-line component; face is driven by personality, not duplication."""

    def __init__(self, state: UIState, context: str = "", *, hide_verb: bool = False):
        self.state = state
        self.hide_verb = hide_verb
        if not context and not hide_verb:
            self.context = UI_STATES[state].label
        else:
            self.context = context

    @property
    def style(self) -> PersonalityStyle:
        return style_of(self.state)

    def _line(self) -> Text:
        """The rendered status line (single Text; measure reuses it)."""
        rec = UI_STATES[self.state]
        style = self.style
        weight = to_style_str(style.weight)
        gap = " " * GAP.status

        glyph = Icon.glyph(style.icon)

        line = Text(style=style.color.to_rich_style())
        line.append(glyph, style=weight or None)
        
        if not self.hide_verb:
            line.append(gap)
            line.append(style.verb, style=weight or None)

        line.append(gap, style=SEMANTIC.text_dim.to_rich_style())
        line.append(self.context, style=SEMANTIC.text_dim.to_rich_style())
        return line

    def __rich_console__(self, console, options) -> RenderableType:
        yield self._line()

    def __rich_measure__(self, console, options):
        """Faithful width so StatusLine composes horizontally inside Row
        (Rich Columns measures via __rich_measure__, else it assumes the
        full console width and stacks items vertically)."""
        from rich.measure import Measurement
        return Measurement.get(console, options, self._line())
