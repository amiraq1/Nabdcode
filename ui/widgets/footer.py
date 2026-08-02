"""AppFooter — navigation hint bar composed from D-1 atoms (Am+8 D-3b)."""

from __future__ import annotations

from rich.console import RenderableType

from ui.design.primitives import Row, KeyValueRow


class AppFooter:
    """Footer displaying active keybindings/hints via atoms."""

    def render(self, active: bool = False) -> RenderableType:
        """Return the footer renderable.

        When *active* is True, shows navigation hints for the result list.
        When *active* is False, shows general REPL hints instead of an empty
        line (behavior change vs NavigationFooter: documented in the D-3b
        commit body).
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
