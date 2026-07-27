"""List container for ToolResultWidget instances.

Owns widget state (selection, current index) and rendering.
Callers (e.g. ``repl_termux.py``) add widgets and never call
``console.print(widget.render())`` directly.

# Navigation constraint:
# next() / previous() only called after show_final_answer
# fires and the REPL is free. While the agent runs inside
# asyncio.to_thread(), no navigation should occur.
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console

from ui.widgets.tool_result import ToolResultWidget


class ToolResultList:
    """Single owner of ToolResultWidget state and rendering.

    * ``add()`` appends without auto-selecting, then redraws.
    * ``next()`` / ``previous()`` wrap around the list.
    * ``current()`` returns the active widget or ``None``.
    * ``redraw()`` is the single source of truth for rendering.
    """

    def __init__(self, console: Optional[Console] = None) -> None:
        self._widgets: list[ToolResultWidget] = []
        self._current_index: int = -1
        self._console: Optional[Console] = console

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def current_index(self) -> int:
        return self._current_index

    def __len__(self) -> int:
        return len(self._widgets)

    # ── Mutation ───────────────────────────────────────────────────────

    def add(self, widget: ToolResultWidget) -> None:
        """Append *widget* (does NOT auto-select) and redraw."""
        self._widgets.append(widget)
        self.redraw()

    def next(self) -> None:
        """Move selection forward (wraps around)."""
        if not self._widgets:
            return
        if self._current_index >= 0:
            self._widgets[self._current_index].deselect()
        if self._current_index == -1:
            self._current_index = 0
        else:
            self._current_index = (self._current_index + 1) % len(self._widgets)
        self._widgets[self._current_index].select()
        self.redraw()

    def previous(self) -> None:
        """Move selection backward (wraps around)."""
        if not self._widgets:
            return
        if self._current_index >= 0:
            self._widgets[self._current_index].deselect()
        if self._current_index == -1:
            self._current_index = len(self._widgets) - 1
        else:
            self._current_index = (self._current_index - 1) % len(self._widgets)
        self._widgets[self._current_index].select()
        self.redraw()

    def current(self) -> Optional[ToolResultWidget]:
        """Return the currently selected widget, or ``None``."""
        if self._current_index < 0 or self._current_index >= len(self._widgets):
            return None
        return self._widgets[self._current_index]

    def toggle_current(self) -> None:
        """Toggle collapse state of the current widget."""
        if self.current() is None:
            return
        self.current().toggle()
        self.redraw()

    def deselect_current(self) -> None:
        """Deselect the current widget and reset selection index (no redraw)."""
        if 0 <= self._current_index < len(self._widgets):
            self._widgets[self._current_index].deselect()
        self._current_index = -1

    def clear(self) -> None:
        """Deselect all widgets, clear the list, reset index."""
        for widget in self._widgets:
            widget.deselect()
        self._widgets.clear()
        self._current_index = -1

    # ── Rendering ──────────────────────────────────────────────────────

    def redraw(self, console: Optional[Console] = None) -> None:
        """Single Source of Truth for rendering.

        Phase 2: prints each widget in order.
        Phase 3: will use Rich Live to update in place.
        """
        if console is None:
            if self._console is not None:
                console = self._console
            else:
                # Lazy import: pick up the live ``console`` from repl_termux
                # (e.g. when tests patch ``ui.repl_termux.console``).
                from ui.repl_termux import console
        for widget in self._widgets:
            console.print(widget.render())
