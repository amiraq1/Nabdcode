"""output_renderer.py — Unified Rich output rendering utilities for TUI/terminal display."""

from __future__ import annotations

from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from core.display import display_json
from core.text_utils import is_arabic, safe_display

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
    info = f"Thought for {sec_int}s"
    if tokens:
        info += f"  •  {tokens} tokens"
    console.print(f"[dim italic]{info}[/dim italic]")


def render_final_answer(text: str) -> None:
    """Render unified final answer box with bidi-aware text alignment."""
    safe_text = safe_display(text)
    justify = "right" if is_arabic(text) else "left"
    console.print(
        Panel(
            Text(safe_text, justify=justify),
            title="[bold magenta]◆ FINAL ANSWER[/bold magenta]",
            border_style="magenta",
            padding=(1, 2),
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
