"""ui/cc_style.py — Claude-Code-style rendering primitives.

Pure functions only; no I/O, no event wiring. UI-CC-2 wires these
into TerminalVisualizer.
"""
from __future__ import annotations

import itertools
from typing import Sequence

BADGE_STYLE = "bold white on #5f5faf"

_STATUS_VERBS = ("Drafting", "Conjuring", "Choreographing",
                 "Abracadabraing", "Crafting")
_verb_cycle = itertools.cycle(_STATUS_VERBS)


def badge_for_tool(tool: str) -> tuple[str, str]:
    """Map a tool name to (LABEL, rich-style) for the badge."""
    t = tool.lower()
    if "read" in t:
        return "READ", BADGE_STYLE
    if any(k in t for k in ("write", "edit", "replace")):
        return "EDIT", BADGE_STYLE
    if "shell" in t:
        return "SHELL", BADGE_STYLE
    if any(k in t for k in ("list", "scan")):
        return "LIST", BADGE_STYLE
    if any(k in t for k in ("search", "web")):
        return "SEARCH", BADGE_STYLE
    if "kill" in t:
        return "KILL", "bold white on red"
    return "TOOL", BADGE_STYLE


def collapse_lines(lines: Sequence[str], keep: int = 3) -> list[str]:
    """Keep first `keep` lines; append a collapse footer if longer."""
    lines = list(lines)
    if len(lines) <= keep:
        return lines
    hidden = len(lines) - keep
    return lines[:keep] + [f"... +{hidden} lines [ctrl+o to expand]"]


def diff_pairs(old: Sequence[str], new: Sequence[str]) -> list[tuple[str, str]]:
    """Line-based diff -> [(sign, text)] with '=', '-', '+'."""
    out: list[tuple[str, str]] = []
    old_set = list(old)
    new_set = list(new)
    for line in old_set:
        if line in new_set:
            out.append(("=", line))
        else:
            out.append(("-", line))
    for line in new_set:
        if line not in old_set:
            out.append(("+", line))
    return out


def todo_line(text: str, done: bool) -> tuple[str, str]:
    """Return (display_text, rich_style) for a todo item."""
    if done:
        return text, "strike green"
    return text, "default"


def format_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def next_status_verb() -> str:
    return next(_verb_cycle)
