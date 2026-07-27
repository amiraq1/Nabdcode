"""Collapsible tool result widget for the NABD agent TUI.

Renders tool outputs as either a full Panel (short output) or a
collapsed header + preview (long output).  Collapse state, line
counting, and preview generation are owned entirely by this widget;
callers (e.g. ``repl_termux.py``) only instantiate and render.

# Navigation constraint:
# Selection state is only meaningful after show_final_answer
# fires and the REPL is free. While the agent runs inside
# asyncio.to_thread(), no selection changes should occur.
"""

from __future__ import annotations

from typing import Any, Optional

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.text import Text

from ui.theme import ACTION_COLORS, PANEL_STYLES, SELECTED_COLOR


class ToolResultWidget:
    """Collapsible tool-result renderer.

    * Output <= ``COLLAPSE_THRESHOLD`` visible (non-empty) lines → full Panel.
    * Output >  ``COLLAPSE_THRESHOLD`` visible lines → collapsed header +
      3-word preview.

    The widget owns collapse state, line counting, preview generation,
    and rendering.  ``toggle()`` is provided for future keyboard shortcuts.
    """

    COLLAPSE_THRESHOLD: int = 5

    def __init__(
        self,
        tool_name: str,
        output: str = "",
        *,
        success: bool = True,
        summary: str = "",
        diff: str = "",
        args: Optional[dict[str, Any]] = None,
        console: Optional[Console] = None,
    ) -> None:
        self.tool_name = tool_name or "?"
        self.output = output or ""
        self.success = success
        self.summary = summary or ""
        self.diff = diff or ""
        self.args = args
        self._console = console or Console()
        self._collapsed: bool = True
        self._line_count: int = 0
        self._preview: str = ""
        self.selected: bool = False

    # ── Public API ─────────────────────────────────────────────────────

    def toggle(self) -> "ToolResultWidget":
        """Flip collapse state and return *self* for chaining."""
        self._collapsed = not self._collapsed
        return self

    def select(self) -> "ToolResultWidget":
        """Mark this widget as selected (highlighted border)."""
        self.selected = True
        return self

    def deselect(self) -> "ToolResultWidget":
        """Clear the selected flag."""
        self.selected = False
        return self

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    @property
    def line_count(self) -> int:
        return self._line_count

    @property
    def preview(self) -> str:
        return self._preview

    def render(self) -> RenderableType:
        """Return the appropriate Rich renderable for the current state."""
        self._count_visible_lines()
        self._generate_preview()

        if self._line_count <= self.COLLAPSE_THRESHOLD or not self._collapsed:
            return self._render_expanded()
        return self._render_collapsed()

    # ── Internal helpers ───────────────────────────────────────────────

    def _count_visible_lines(self) -> None:
        """Count non-empty lines in the output."""
        self._line_count = sum(1 for line in self.output.splitlines() if line.strip())

    def _generate_preview(self) -> None:
        """Build a short preview: first non-empty line, max 3 words."""
        lines = [line for line in self.output.splitlines() if line.strip()]
        if not lines:
            self._preview = ""
            return
        words = lines[0].split()
        preview = " ".join(words[:3])
        if len(words) > 3:
            preview += "..."
        self._preview = preview

    def _get_badge(self) -> str:
        """Determine the badge label using the existing theme helper."""
        from engine.ui_theme import map_tool_to_badge

        return map_tool_to_badge(self.tool_name, self.args)

    def _get_badge_color(self) -> str:
        """Return the hex color for the badge from ACTION_COLORS."""
        badge = self._get_badge()
        return ACTION_COLORS.get(badge, ACTION_COLORS.get("USER", "#0891B2"))

    def _get_info(self) -> str:
        """Return the parenthesised info string shown in the header."""
        if not self.output.strip():
            return "clean"
        return f"{self._line_count} lines"

    def _build_header_markup(self) -> str:
        """Compose the collapsed header as Rich markup."""
        badge = self._get_badge()
        color = self._get_badge_color()
        status = "✓" if self.success else "✗"
        status_style = "green" if self.success else "red"
        info = self._get_info()
        return (
            f"► [#{color}]{badge}[/]  "
            f"{self.tool_name}  "
            f"[{status_style}]{status}[/]  "
            f"({info})"
        )

    def _render_expanded(self) -> RenderableType:
        """Full output Panel — preserves existing rendering behavior."""
        output_text = self.output.strip() if self.output else "(empty result)"
        if len(output_text) > 2000:
            output_text = output_text[:2000] + "\n...[truncated by UI]"
        border = SELECTED_COLOR if self.selected else PANEL_STYLES["tool_complete"]["border_style"]
        return Panel(
            Text(f"[{self.tool_name}]\n{output_text}", style="white"),
            border_style=border,
            title=PANEL_STYLES["tool_complete"]["title"],
            padding=PANEL_STYLES["tool_complete"]["padding"],
        )

    def _render_collapsed(self) -> RenderableType:
        """Collapsed header + preview Panel."""
        header = self._build_header_markup()
        parts: list[str] = [header]
        if self._preview:
            parts.append(f"[dim]{self._preview}[/dim]")
        content = "\n".join(parts)
        border = SELECTED_COLOR if self.selected else "cyan"
        return Panel(
            Text.from_markup(content),
            border_style=border,
            padding=(0, 1),
        )
