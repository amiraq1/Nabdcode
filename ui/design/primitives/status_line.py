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
    PersonalityStyle, style_of, spinner_frame_for, to_style_str,
)


class StatusLine:
    """Single status-line component; face is driven by personality, not duplication."""

    def __init__(self, state: UIState, context: str = ""):
        self.state = state
        self.context = context or UI_STATES[state].label

    @property
    def style(self) -> PersonalityStyle:
        return style_of(self.state)

    def __rich_console__(self, console, options) -> RenderableType:
        rec = UI_STATES[self.state]
        style = self.style
        weight = to_style_str(style.weight)
        gap = " " * GAP.status

        line = Text(style=style.color.to_rich_style())
        line.append(Icon.glyph(style.icon), style=weight or None)
        line.append(gap)
        line.append(style.verb, style=weight or None)

        frame = spinner_frame_for(self.state)
        if frame:
            line.append(gap)
            line.append(frame, style=weight or None)

        line.append(gap, style=SEMANTIC.text_dim.to_rich_style())
        line.append(self.context, style=SEMANTIC.text_dim.to_rich_style())
        yield line
