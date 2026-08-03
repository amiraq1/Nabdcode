"""Collapsible tool result widget — D-2: consumes D-1 primitives.

Rendering is composed exclusively from design atoms: Gutter (fixed-width
selection/collapse slots), StatusLine (result state), SectionPanel
(container), Badge (tool label), KeyValueRow (metadata), Divider
(separator), Row/Column (layout).
Colors arrive only via SEMANTIC; this file carries no hex values, no color
names, and constructs no rich Style. Collapse state, line counting, and
preview generation remain data owned by this widget; callers (e.g.
``repl_termux.py``) only instantiate and render.

# Navigation constraint:
# Selection state is only meaningful after show_final_answer
# fires and the REPL is free. While the agent runs inside
# asyncio.to_thread(), no selection changes should occur.
"""
from __future__ import annotations

from typing import Any, Optional

from rich.console import Console, RenderableType
from rich.syntax import Syntax
from rich.text import Text

from engine.ui_theme import map_tool_to_badge
from ui.design.primitives import (
    Badge,
    Column,
    Divider,
    Gutter,
    KeyValueRow,
    Row,
    SectionPanel,
    StatusLine,
)
from ui.design.state import UIState
from ui.design.theme.semantic import SEMANTIC

# Tool badge label -> Badge meaning (semantic vocabulary, not a palette).
_BADGE_MEANING: dict[str, str] = {
    "WARNING": "warning",
    "KILL": "error",
    "FINAL ANSWER": "success",
    "GIT": "success",
}


class ToolResultWidget:
    """Collapsible tool-result renderer built from D-1 primitives.

    * Output <= ``COLLAPSE_THRESHOLD`` visible (non-empty) lines -> full Panel.
    * Output >  ``COLLAPSE_THRESHOLD`` visible lines -> collapsed header +
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
        """Return the composed SectionPanel for the current state."""
        self._count_visible_lines()
        self._generate_preview()

        if self._line_count <= self.COLLAPSE_THRESHOLD or not self._collapsed:
            return self._render_expanded()
        return self._render_collapsed()

    # ── Data helpers (state, not rendering) ────────────────────────────

    def _get_deduplicated_lines(self) -> list[str]:
        """Return output lines, stripping the reason if it is the first line."""
        lines = self.output.splitlines()
        if self.success:
            return lines
            
        reason = self._reason()
        if not reason:
            return lines
            
        first_non_empty = next((i for i, l in enumerate(lines) if l.strip()), -1)
        if first_non_empty != -1 and lines[first_non_empty].strip() == reason:
            return lines[:first_non_empty] + lines[first_non_empty+1:]
            
        return lines

    def _count_visible_lines(self) -> None:
        """Count non-empty lines in the output, estimating visual word-wrap."""
        lines = 0
        w = 80
        if self._console is not None:
            _cw = getattr(self._console, "width", None)
            if isinstance(_cw, int) and _cw > 0:   # robust vs MagicMock / non-int width
                w = _cw
        w = max(40, w)  # minimum width sanity check to avoid excessive counts

        for line in self._get_deduplicated_lines():
            if not line.strip():
                continue
            # V-07a: each visual wrap adds a line to the visible count
            lines += 1 + (len(line) // w)

        self._line_count = lines

    def _generate_preview(self) -> None:
        """Build a short preview: first non-empty line, max 3 words."""
        lines = [line.strip() for line in self._get_deduplicated_lines() if line.strip()]
        if not lines:
            self._preview = ""
            return
        words = lines[0].split()
        preview = " ".join(words[:3])
        if len(words) > 3:
            preview += "..."
        self._preview = preview

    def _get_badge(self) -> str:
        """Map the tool name to its badge label (pure data mapping)."""
        return map_tool_to_badge(self.tool_name, self.args)

    def _get_info(self) -> str:
        """Return the info string shown in the header."""
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

    # ── Semantic resolution (colors only via SEMANTIC) ─────────────────

    def _state(self) -> UIState:
        """Result state: SUCCESS or ERROR (the two terminal personalities)."""
        return UIState.SUCCESS if self.success else UIState.ERROR

    def _badge_meaning(self) -> str:
        """Semantic meaning for the tool badge (never a raw color)."""
        return _BADGE_MEANING.get(self._get_badge(), "info")

    def _border_color(self):
        """Border resolves through SEMANTIC: result state only (D-3c.2:
        selection moved to the SelectionIndicator atom — strict replace)."""
        return SEMANTIC.success if self.success else SEMANTIC.error

    def _reason(self) -> str:
        """Named error reason segment: exception message > stderr > exit code."""
        if self.success:
            return ""
        if self.summary:
            return self.summary
            
        lines = [line.strip() for line in self.output.splitlines() if line.strip()]
        if not lines:
            return ""
            
        if "Traceback (most recent call last):" in self.output:
            return lines[-1]
            
        for line in lines:
            lower = line.lower()
            if lower.startswith(("error:", "fatal:", "exception:")):
                return line
                
        for line in reversed(lines):
            if "exit code" in line.lower():
                return line
                
        return ""

    # ── Composition (atoms only) ───────────────────────────────────────

    def _header(self, collapsed: bool) -> Row:
        """Header row: fixed-width gutter (selection + collapse slots), then
        the status/result line and the tool badge. The gutter (D-3c.3) keeps
        the status glyph at a stable column across every (selected x collapsed)
        combination, so the list never shakes horizontally."""
        return Row(
            Gutter(selected=self.selected, collapsed=collapsed),
            StatusLine(self._state(), context=self._get_info()),
            Badge(self._get_badge(), self._badge_meaning()),
        )

    def _body(self):
        """Output body: Syntax for tracebacks, else a semantic Text."""
        deduplicated = "\n".join(self._get_deduplicated_lines())
        output_text = deduplicated.strip() if deduplicated.strip() else "(empty result)"

        # V-07a: truncate at line boundaries instead of raw mid-line cutting
        MAX_LEN = 2000
        if len(output_text) > MAX_LEN:
            truncated = output_text[:MAX_LEN]
            last_newline = truncated.rfind("\n")
            if last_newline > 0:
                output_text = truncated[:last_newline] + "\n...[truncated by UI]"
            else:
                output_text = truncated + "\n...[truncated by UI]"

        # V-03: semantic traceback coloring
        if "Traceback (most recent call last):" in output_text:
            return Syntax(output_text, "pytb", theme="monokai", word_wrap=True)

        # V-07a: ellipsis overflow + no_wrap prevents path tearing on narrow screens
        return Text(
            output_text,
            style=SEMANTIC.text.to_rich_style(),
            overflow="ellipsis",
            no_wrap=True,
        )

    def _render_expanded(self) -> SectionPanel:
        """Full output panel — header, reason, separator, then the body."""
        parts = [self._header(collapsed=False)]
        if self._format_args_preview():
            parts.append(KeyValueRow("arg", self._format_args_preview()))
        if not self.success and self._reason():
            parts.append(KeyValueRow("reason", self._reason()))
        parts.append(Divider())
        parts.append(self._body())
        return SectionPanel(
            title=self.tool_name,
            content=Column(*parts),
            border_color=self._border_color(),
        )

    def _render_collapsed(self) -> SectionPanel:
        """Collapsed header + preview panel (same skeleton as expanded)."""
        parts = [self._header(collapsed=True)]
        if self._format_args_preview():
            parts.append(KeyValueRow("arg", self._format_args_preview()))
        if not self.success and self._reason():
            parts.append(KeyValueRow("reason", self._reason()))
        parts.append(Divider())
        if self._preview:
            parts.append(Text(
                self._preview,
                style=SEMANTIC.text_muted.to_rich_style(),
            ))
        return SectionPanel(
            title=self.tool_name,
            content=Column(*parts),
            border_color=self._border_color(),
        )
