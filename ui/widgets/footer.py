"""Navigation footer help widget (Phase 4).

Renders a short hint bar showing the available keyboard shortcuts when
navigation is active (after ``show_final_answer``).  When navigation is
inactive the footer renders as an empty ``Text`` so nothing is printed.
"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ui.theme import FOOTER_COLOR


class NavigationFooter:
    """Minimal footer that shows/hides navigation hint text."""

    def render(self, active: bool) -> RenderableType:
        """Return the footer renderable.

        When *active* is ``False`` an empty ``Text`` is returned so the
        caller can safely ``console.print()`` without producing output.
        """
        if not active:
            return Text("")
        return Text(
            "  Navigate: j/k \u2191\u2193   Expand: Enter   Exit: Esc",
            style=FOOTER_COLOR,
        )
