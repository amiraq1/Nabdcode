"""Checklist widget for Todo and plan display."""

from __future__ import annotations

from typing import Any, List, Dict
from textual.widgets import Static


class TodoBlock(Static):
    """Widget displaying active plan / Todo items."""

    def __init__(self, todos: List[Dict[str, Any]] | None = None, **kwargs: Any) -> None:
        self.todos = todos or []
        super().__init__(self._format_todos(), classes="todo-block", **kwargs)

    def _format_todos(self) -> str:
        if not self.todos:
            return "📋 No active plan items."
        lines = ["📋 CURRENT PLAN:"]
        for t in self.todos:
            status = t.get("status", "pending")
            mark = "x" if status in ("done", "completed") else ("/" if status == "in_progress" else " ")
            desc = t.get("description", t.get("task", "Unknown task"))
            lines.append(f"  [{mark}] {desc}")
        return "\n".join(lines)

    def update_todos(self, todos: List[Dict[str, Any]]) -> None:
        self.todos = todos
        self.update(self._format_todos())
