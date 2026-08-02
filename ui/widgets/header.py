"""AppHeader — application header composed from D-1 atoms (Am+8 D-3b).

Replaces the manual logo/status ``console.print`` block in ``run_repl``:
logo Text + a status Row of Badge/KeyValueRow, centered, all colors via
SEMANTIC (no hex literals in this file). The blank line between logo and
status row and the group separators come from tokens, never literals.
"""
from __future__ import annotations

import os
from typing import Optional

from rich.align import Align
from rich.console import RenderableType
from rich.text import Text

from ui.design.primitives import Column, Row, Badge, KeyValueRow
from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import GAP, SEPARATOR


class AppHeader:
    """Main application header: logo + session metadata."""

    def __init__(
        self,
        workspace: Optional[str] = None,
        model: str = "gemini-1.5-pro",
    ) -> None:
        self.workspace = workspace or os.path.basename(os.getcwd())
        self.model = model

    def render(self) -> RenderableType:
        """Return the header layout using atoms (logo + status row)."""
        logo = Text(style=SEMANTIC.text.to_rich_style())
        logo.append("█▄ █ ▄▀█ █▄▀ █▀▄ █▀▀ █▀█ █▀▄ █▀▀\n")
        logo.append(
            "█ ▀█ █▀█ █▄█ █▄▀ █▄▄ █▄█ █▄▀ ██▄",
            style=SEMANTIC.text_dim.to_rich_style(),
        )

        status_row = Row(
            Badge("System Ready", meaning="success"),
            KeyValueRow("Model", self.model),
            KeyValueRow("Workspace", self.workspace),
            separator=SEPARATOR.group,
        )

        return Column(
            Align.center(logo),
            Text("\n" * GAP.header_after_logo),
            Align.center(status_row),
        )
