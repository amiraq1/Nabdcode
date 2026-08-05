"""D-1 SectionPanel: unified bordered container (native Rich renderable).

Borders via rich.Panel with SEMANTIC-derived style; any Rich renderable can be
the content (Group / Text / another atom) — Rich owns measurement, so there is
no width math here.
"""
from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from ui.design.theme.color import Color
from ui.design.theme.semantic import SEMANTIC
from ui.design.typography import PRESETS


class SectionPanel:
    """A Rich bordered panel; border color resolves through SEMANTIC."""

    def __init__(self, title: str, content, border_color: Color | None = None):
        self.title = title
        self.content = content
        self.border_color = border_color or SEMANTIC.border

    def __rich_console__(self, console, options):
        title_style = PRESETS["section_title"].color.to_rich_style()
        panel = Panel(
            self.content,
            title=Text(self.title, style=title_style),
            border_style=self.border_color.to_rich_style(),
        )
        yield panel
