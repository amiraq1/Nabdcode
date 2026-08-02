"""Application footer and navigation hint widget (Phase D-3b)."""

from __future__ import annotations

from rich.console import RenderableType

from ui.design.primitives import Row, KeyValueRow


class AppFooter:
    """Footer displaying active keybindings/hints via atoms."""

    def render(self, active: bool = False) -> RenderableType:
        """Return the footer renderable.

        When *active* is False, returns general repl hints.
        When *active* is True, returns navigation hints.
        """
        if active:
            return Row(
                KeyValueRow("Navigate", "j/k ↑↓"),
                KeyValueRow("Expand", "Enter"),
                KeyValueRow("Exit", "Esc"),
            )
            
        return Row(
            KeyValueRow("Input", "[shift+tab]"),
            KeyValueRow("Help", "? for shortcuts"),
        )
