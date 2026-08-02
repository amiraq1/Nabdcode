"""D-1 Spinner: single implementation, native Rich renderable, static frame.

Reads the timing rate as a numeric VALUE from AnimationSpec.speed (a float
sourced from tokens.AnimationSpeed). Motion / animation loop is deferred (the
rendered frame is static). No loop, no thread, no polling.
"""
from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from ui.design.animation import AnimationSpec, Spinner as SpinnerEnum
from ui.design.icons import Icon
from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import GAP


_FRAME_FOR: dict[SpinnerEnum, str] = {
    SpinnerEnum.NONE:    "",
    SpinnerEnum.DOTS:    Icon.glyph(Icon.LOADING),
    SpinnerEnum.LINE:    Icon.glyph(Icon.RUNNING),
    SpinnerEnum.ELAPSE:  Icon.glyph(Icon.WAITING),
    SpinnerEnum.PULSE:   Icon.glyph(Icon.THINKING),
    SpinnerEnum.WAVE:    Icon.glyph(Icon.THINKING),
    SpinnerEnum.BRAILLE: Icon.glyph(Icon.STREAMING),
}


class Spinner:
    """Static, single-frame spinner. Rate is exposed as a value for consumers."""

    def __init__(self, spec: AnimationSpec):
        self.spec = spec

    @property
    def rate(self) -> float:
        """The numeric timing value (seconds) read from D-0 tokens."""
        return self.spec.speed

    def __rich_console__(self, console, options) -> RenderableType:
        glyph = _FRAME_FOR.get(self.spec.spinner, "")
        line = Text()
        if glyph:
            line.append(glyph, style=SEMANTIC.info.to_rich_style())
            line.append(" " * GAP.status)
        line.append("{:.2f}s".format(self.rate), style=SEMANTIC.caption.to_rich_style())
        yield line
