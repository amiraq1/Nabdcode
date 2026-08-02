"""D-1 KeyValueRow: key/value row (native Rich renderable).

Truncation delegates to rich.text.Text.truncate + cell_len — Rich owns the
display-cell math (wcwidth included). No manual alignment; direction-agnostic.
"""
from __future__ import annotations

from rich.cells import cell_len as rich_cell_len
from rich.text import Text

from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import GAP


class KeyValueRow:
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

    def __rich_console__(self, console, options):
        max_width = options.max_width
        gap_count = GAP.status

        key_w = rich_cell_len(self.key)
        avail = max(max_width - key_w - gap_count, 0)

        value_text = Text(self.value, style=SEMANTIC.text_dim.to_rich_style())
        if value_text.cell_len > avail and avail > 1:
            value_text.truncate(avail, overflow="ellipsis")
        elif avail <= 1:
            value_text = Text("", style=SEMANTIC.text_dim.to_rich_style())

        line = Text(self.key + (" " * gap_count), style=SEMANTIC.text.to_rich_style())
        line.append(value_text)
        yield line
