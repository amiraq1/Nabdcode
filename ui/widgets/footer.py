"""AppFooter — navigation hint bar composed from D-1 atoms (Am+8 D-3b)."""

from __future__ import annotations

from rich.console import RenderableType
from rich.padding import Padding

from ui.design.primitives import Row, KeyValueRow
from ui.design.tokens import GAP, SEPARATOR


class AppFooter:
    """Footer displaying active keybindings/hints via atoms."""

    def _row(self, active: bool) -> Row:
        if active:
            return Row(
                KeyValueRow("Navigate", "j/k ↑↓"),
                KeyValueRow("Expand", "Enter"),
                KeyValueRow("Exit", "Esc"),
                separator=SEPARATOR.group,
            )
        return Row(
            KeyValueRow("Input", "[shift+tab]"),
            KeyValueRow("Help", "? for shortcuts"),
            separator=SEPARATOR.group,
        )

    def render(self, active: bool = False) -> RenderableType:
        """Return the footer renderable (group separators + leading indent
        come from tokens, never literals).

        When *active* is True, shows navigation hints for the result list.
        When *active* is False, shows general REPL hints instead of an empty
        line (behavior change vs NavigationFooter: documented in the D-3b
        commit body).
        """
        return Padding(self._row(active), (0, 0, 0, GAP.footer_indent))
