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

from rich.syntax import Syntax

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
        """Count non-empty lines in the output, estimating visual word-wrap on narrow terminals."""
        lines = 0
        # If no console attached or width unavailable, fallback to 80 chars.
        # Narrow phones often sit around 40-50, but 80 is a safe conservative estimate.
        w = 80
        if self._console is not None:
            _cw = getattr(self._console, "width", None)
            if isinstance(_cw, int) and _cw > 0:   # robust vs MagicMock / non-int width
                w = _cw
        w = max(40, w) # Minimum width sanity check to avoid excessive counts
        
        for line in self.output.splitlines():
            if not line.strip():
                continue
            # V-07a: Each visual wrap adds a line to the visible count
            lines += 1 + (len(line) // w)
            
        self._line_count = lines

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
        
    def _format_args_preview(self) -> str:
        """Extract a meaningful path or command from args and truncate it."""
        if not self.args:
            return ""
            
        target = (
            self.args.get("path") or 
            self.args.get("file") or 
            self.args.get("target") or 
            self.args.get("TargetFile") or 
            self.args.get("AbsolutePath") or 
            self.args.get("DirectoryPath")
        )
        
        if not target and self.args.get("command"):
            target = self.args.get("command")
        elif not target and self.args.get("CommandLine"):
            target = self.args.get("CommandLine")
            
        if not isinstance(target, str):
            return ""
            
        # Smart truncation in the middle if > 40 chars
        MAX_LEN = 40
        if len(target) > MAX_LEN:
            half = (MAX_LEN - 3) // 2
            target = target[:half] + "..." + target[-half:]
            
        return target

    def _build_header_markup(self) -> str:
        """Compose the collapsed header as Rich markup."""
        badge = self._get_badge()
        color = self._get_badge_color()
        status = "✓" if self.success else "✗"
        status_style = "green" if self.success else "red"
        info = self._get_info()
        
        arg_preview = self._format_args_preview()
        arg_markup = f" [cyan]{arg_preview}[/]" if arg_preview else ""
        
        return (
            f"► [#{color}]{badge}[/]  "
            f"{self.tool_name}{arg_markup}  "
            f"[{status_style}]{status}[/]  "
            f"({info})"
        )

    def _render_expanded(self) -> RenderableType:
        """Full output Panel — preserves existing rendering behavior."""
        output_text = self.output.strip() if self.output else "(empty result)"
        
        # V-07a: Smart truncation at line boundaries instead of raw mid-line cutting
        MAX_LEN = 2000
        if len(output_text) > MAX_LEN:
            truncated = output_text[:MAX_LEN]
            last_newline = truncated.rfind('\n')
            if last_newline > 0:
                output_text = truncated[:last_newline] + "\n...[truncated by UI]"
            else:
                output_text = truncated + "\n...[truncated by UI]"
            
        # V-03: Semantic traceback coloring
        if "Traceback (most recent call last):" in output_text:
            content = Syntax(output_text, "pytb", theme="monokai", word_wrap=True)
        else:
            # V-07a: Use ellipsis overflow and no_wrap to prevent ugly path tearing on narrow screens
            content = Text(f"[{self.tool_name}]\n{output_text}", style="white", overflow="ellipsis", no_wrap=True)
            
        border = SELECTED_COLOR if self.selected else PANEL_STYLES["tool_complete"]["border_style"]
        return Panel(
            content,
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
