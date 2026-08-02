"""Final answer widget (Phase D-3c)."""

from __future__ import annotations

from rich.console import RenderableType
from rich.markdown import Markdown

from ui.design.primitives import SectionPanel
from ui.design.theme.semantic import SEMANTIC


class FinalAnswer:
    """Widget displaying the agent's final answer via atoms."""

    def __init__(self, content: str, title: str = "◆ FINAL ANSWER") -> None:
        self.content = content
        self.title = title

    def render(self) -> RenderableType:
        """Return the final answer layout using primitives."""
        return SectionPanel(
            title=self.title,
            content=Markdown(self.content),
            border_color=SEMANTIC.primary,
        )
