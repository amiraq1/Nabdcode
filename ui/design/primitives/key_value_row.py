"""D-1 KeyValueRow: key/value row (native Rich renderable).

Truncation delegates to rich.text.Text.truncate + cell_len — Rich owns the
display-cell math (wcwidth included). No manual alignment; direction-agnostic.
The key/value delimiter is the SEPARATOR.key_value token (glyph + SEMANTIC
color) — this atom draws it, no widget types one.
"""
from __future__ import annotations

from rich.cells import cell_len as rich_cell_len
from rich.text import Text

from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import GAP, SEPARATOR


class KeyValueRow:
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

    def _line(self, max_width: int) -> Text:
        gap_count = GAP.status
        delimiter = SEPARATOR.key_value

        key_w = rich_cell_len(self.key) + rich_cell_len(delimiter.glyph)
        avail = max(max_width - key_w - gap_count, 0)

        value_text = Text(self.value, style=SEMANTIC.text_dim.to_rich_style())
        if value_text.cell_len > avail and avail > 1:
            value_text.truncate(avail, overflow="ellipsis")
        elif avail <= 1:
            value_text = Text("", style=SEMANTIC.text_dim.to_rich_style())

        line = Text(self.key, style=SEMANTIC.text.to_rich_style())
        line.append(delimiter.glyph, style=delimiter.color.to_rich_style())
        line.append(" " * gap_count, style=SEMANTIC.text.to_rich_style())
        line.append(value_text)
        return line

    def __rich_console__(self, console, options):
        yield self._line(options.max_width)

    def __rich_measure__(self, console, options):
        """Faithful width (same truncation as render) for Row composition."""
        from rich.measure import Measurement
        return Measurement.get(console, options, self._line(options.max_width))
