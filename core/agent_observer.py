from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class AgentObserver(ABC):
    """Abstract observer for agent lifecycle events.

    Any future UI (GUI, Web, Textual, API) subscribes by subclassing
    this and registering via ``set_observers`` on the bridge. Every
    hook is invoked through the bridge's fail-safe ``_notify_observers``
    wrapper, so a crashing observer can NEVER halt the main OS.

    Naming convention matches the bridge's existing sync-observer API
    (on_agent_thought, on_action_triggered, on_status_changed,
    on_plan_updated, on_file_modified) so the adapter maps 1:1.
    """

    @abstractmethod
    def on_agent_thought(self, thought: str) -> None:
        """Called to surface agent reasoning text."""
        raise NotImplementedError

    @abstractmethod
    def on_action_triggered(
        self, action_type: str, target: str, meta: str = ""
    ) -> None:
        """Called when a tool/step fires (READ, SHELL, AGENT, USER, ...)."""
        raise NotImplementedError

    @abstractmethod
    def on_status_changed(self, status_text: str) -> None:
        """Called to update the status bar / progress text."""
        raise NotImplementedError

    @abstractmethod
    def on_plan_updated(self, todos: List[Dict[str, Any]]) -> None:
        """Called when the task plan / TodoManager changes."""
        raise NotImplementedError

    @abstractmethod
    def on_file_modified(self, diff_content: str) -> None:
        """Called when a file is written/edited via FileSystemTool."""
        raise NotImplementedError
