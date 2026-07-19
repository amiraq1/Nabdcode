"""UI Badges and Collapsible Blocks for Action/Thought representation."""

from __future__ import annotations

from typing import Any
from textual.widgets import Static, Collapsible
from ui.widgets.collapsible_tool import create_thought_block


class ActionTag(Static):
    """Badge representation for tool/action execution status."""

    def __init__(
        self,
        action: str,
        target: str = "",
        status: str = "in_progress",
        meta: str = "",
        **kwargs: Any,
    ) -> None:
        self.action = action
        self.target = target
        self.status = status
        self.meta = meta
        super().__init__(self._format_label(), classes=f"action-tag action-{status}", **kwargs)

    def _format_label(self) -> str:
        icon = "⏳" if self.status == "in_progress" else ("✅" if self.status == "success" else "❌")
        target_str = f" [{self.target}]" if self.target else ""
        return f"{icon} ⚡ {self.action}{target_str} ({self.status})"

    def update_status(self, new_status: str) -> None:
        self.remove_class(f"action-{self.status}")
        self.status = new_status
        self.add_class(f"action-{new_status}")
        self.update(self._format_label())


class AgentThought(Collapsible):
    """Collapsible Bento block representation for agent reasoning."""

    def __init__(self, thought_text: str, step: int = 1, collapsed: bool = True, **kwargs: Any) -> None:
        self.thought_text = thought_text
        content = Static(thought_text, classes="thought-block-content")
        title = f"🧠 THOUGHT (Click to Expand)"
        super().__init__(content, title=title, collapsed=collapsed, classes="bento-thought-block", **kwargs)
