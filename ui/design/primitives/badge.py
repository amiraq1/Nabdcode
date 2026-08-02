"""D-1 Badge: a semantic label chip (native Rich renderable)."""
from __future__ import annotations

from rich.text import Text

from ui.design.theme.semantic import SEMANTIC


_MEANING_COLOR = {
    "info":    SEMANTIC.info,
    "success": SEMANTIC.success,
    "warning": SEMANTIC.warning,
    "error":   SEMANTIC.danger,
    "muted":   SEMANTIC.text_muted,
}


class Badge:
    def __init__(self, text: str, meaning: str = "info"):
        self.text = text
        self.meaning = meaning

    def _line(self) -> Text:
        color = _MEANING_COLOR.get(self.meaning, SEMANTIC.info)
        line = Text(style=SEMANTIC.text_dim.to_rich_style())
        line.append("[")
        line.append(self.text, style=color.to_rich_style())
        line.append("]")
        return line

    def __rich_console__(self, console, options):
        yield self._line()

    def __rich_measure__(self, console, options):
        """Faithful width so Badge composes horizontally inside Row."""
        from rich.measure import Measurement
        return Measurement.get(console, options, self._line())
