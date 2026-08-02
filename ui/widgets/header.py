"""Application header widget (Phase D-3b)."""

from __future__ import annotations

import os
from typing import Optional

from rich.align import Align
from rich.console import RenderableType
from rich.text import Text

from ui.design.primitives import Column, Row, Badge, KeyValueRow
from ui.design.theme.semantic import SEMANTIC


class AppHeader:
    """Main application header displaying logo and session metadata."""

    def __init__(self, workspace: Optional[str] = None, model: str = "gemini-1.5-pro") -> None:
        self.workspace = workspace or os.path.basename(os.getcwd())
        self.model = model

    def render(self) -> RenderableType:
        """Return the header layout using primitives."""
        logo = Text.from_markup(
            f"[{SEMANTIC.text}]█▄ █ ▄▀█ █▄▀ █▀▄ █▀▀ █▀█ █▀▄ █▀▀[/]\n"
            f"[{SEMANTIC.dim}]█ ▀█ █▀█ █▄█ █▄▀ █▄▄ █▄█ █▄▀ ██▄[/]"
        )
        
        status_row = Row(
            Badge("System Ready", meaning="success"),
            KeyValueRow("Model", self.model),
            KeyValueRow("Workspace", self.workspace),
        )
        
        return Column(
            Align.center(logo),
            Align.center(status_row)
        )
