"""display.py — Smart JSON and structured data display utilities with long path abbreviation."""

from __future__ import annotations

import json
from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()


def shorten_paths(obj: Any) -> Any:
    """Recursively shorten long absolute Termux/Android paths inside data structures."""
    if isinstance(obj, dict):
        return {k: shorten_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shorten_paths(i) for i in obj]
    if isinstance(obj, str) and obj.startswith("/data/data/com.termux"):
        parts = [p for p in obj.split("/") if p]
        return "~/" + "/".join(parts[-2:]) if len(parts) > 2 else obj
    return obj


def display_json(data: dict | list | str | Any, title: str = "") -> None:
    """Display JSON or structured data with smart wrapping and path abbreviation."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            console.print(data)
            return

    cleaned = shorten_paths(data)
    try:
        formatted = json.dumps(cleaned, indent=2, ensure_ascii=False)
    except TypeError:
        formatted = str(cleaned)

    syntax = Syntax(formatted, "json", theme="monokai", word_wrap=True)
    if title:
        console.print(Panel(syntax, title=title, border_style="dim"))
    else:
        console.print(syntax)
