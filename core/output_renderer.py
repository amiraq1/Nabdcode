"""output_renderer.py — Unified Rich output rendering utilities for TUI/terminal display."""

from __future__ import annotations

from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from core.display import display_json
from core.text_utils import is_arabic, safe_display, display_width, wrap_text

console = Console()

# ── Unified teal / ice-blue palette ────────────────────────────────────────
ICE_BLUE = "#0891B2"                # cyan-600 — primary badge color
ICE_BLUE_LIGHT = "#22D3EE"          # cyan-400 — lighter variant
ICE_BLUE_MID = "#06B6D4"            # cyan-500 — medium variant
ICE_BLUE_DARK = "#0E7490"           # cyan-700 — darker variant


def render_badge(label: str, text: str = "") -> None:
    """Render a teal-background badge (e.g. ` USER `) with optional trailing text."""
    if text:
        console.print(
            f"[bold white on {ICE_BLUE}] {label} [/bold white on {ICE_BLUE}]"
            f" [dim]{text}[/dim]"
        )
    else:
        console.print(f"[bold white on {ICE_BLUE}] {label} [/bold white on {ICE_BLUE}]")


def render_thinking(seconds: int | float, tokens: int = 0) -> None:
    """Render standardized thinking duration and token counts."""
    sec_int = int(seconds) if isinstance(seconds, (int, float)) else seconds
    info = f"Thinking  {sec_int}s"
    if tokens:
        info += f"  •  {tokens} tokens"
    console.print(f"[dim italic]{info}[/dim italic]")


def render_final_answer(text: str) -> None:
    """Render unified final answer box with bidi-aware text alignment.

    Arabic text is preserved in its original Unicode order internally;
    only display-only directional isolation is applied here via ``safe_display``.
    Width is computed using ``display_width()`` (not ``len()``) so Arabic
    and wide characters are measured correctly on narrow Termux screens.
    """
    safe_text = safe_display(text)
    justify = "right" if is_arabic(text) else "left"
    # Compute safe width using display_width, capped to console width.
    console_width = console.size.width if hasattr(console, "size") else 80
    safe_width = min(display_width(text), console_width - 4)
    safe_width = max(safe_width, 20)  # minimum width
    console.print(
        Panel(
            Text(safe_text, justify=justify),
            title="[bold magenta]◆ FINAL ANSWER[/bold magenta]",
            border_style="magenta",
            padding=(1, 2),
            width=safe_width,
        )
    )


def render_tool_output(data: Any, tool_name: str = "") -> None:
    """Render tool outputs cleanly using JSON syntax wrapping when structured."""
    if isinstance(data, (dict, list)):
        display_json(data, title=tool_name)
    else:
        prefix = f"[dim]{tool_name}:[/dim] " if tool_name else ""
        console.print(f"{prefix}{data}")


def render_error(msg: str) -> None:
    """Render prominent error notification box."""
    console.print(Panel(f"[red]{msg}[/red]", title="Error", border_style="red"))
