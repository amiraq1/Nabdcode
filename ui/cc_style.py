"""ui/cc_style.py — Claude-Code-style rendering primitives.

Pure functions only; no I/O, no event wiring. UI-CC-2 wires these
into TerminalVisualizer.
"""
from __future__ import annotations

import itertools
from typing import Sequence

from ui.design.theme.semantic import SEMANTIC

# Badge background routes through the semantic palette (no raw #hex).
BADGE_STYLE = f"bold white on {SEMANTIC.action_badge}"

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


# ── UI-CC-2: header / thought / status lines ───────────────────────────────

def _primary_arg(args: dict | None) -> str:
    """Pick the primary argument for a tool header line.

    Priority: path, filepath, file, command, query, url; falls back to the
    first string value.  Clamped to 60 characters.
    """
    if not isinstance(args, dict):
        return ""
    for key in ("path", "filepath", "file", "command", "query", "url", "target"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:60]
    for val in args.values():
        if isinstance(val, str) and val.strip():
            return val.strip()[:60]
    return ""


def tool_header_line(tool: str, args: dict | None = None) -> str:
    """Build a Claude-Code-style tool header line: ``BADGE  primary-arg``.

    Returns a plain string like ``READ  main.py``.  The badge label is
    derived from :func:`badge_for_tool`; the argument from
    :func:`_primary_arg`.
    """
    label, _style = badge_for_tool(tool)
    primary = _primary_arg(args)
    if primary:
        return f"{label}  {primary}"
    return label


def thought_line(seconds: int) -> str:
    """Format the thought indicator with an elapsed-seconds count."""
    unit = "second" if seconds == 1 else "seconds"
    return f"✳ Thought for {seconds} {unit} [ctrl+o to expand]"


def status_line(verb: str, tokens: int) -> str:
    """Format a status line with a verb and a human-readable token count."""
    return f"✦ {verb}… {format_tokens(tokens)}"
