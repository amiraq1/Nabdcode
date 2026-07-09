"""ui_theme.py — Cursor-like TUI theme for Nabdcode (Termux-safe ANSI 256).

Palette, badge pills, tool headers, collapsed blocks, diff rendering,
TODO checklist, thought line, status chip — all stateless helpers.
"""

from __future__ import annotations

import difflib
import shutil
from typing import Any, Optional

# ── ANSI shortcuts ──────────────────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_STRIKE = "\033[9m"


def _ansi(r: int, g: int, b: int, fg: bool = True) -> str:
    return f"\033[{38 if fg else 48};2;{r};{g};{b}m"


def fg(*rgb: int) -> str:
    return _ansi(*rgb, fg=True)


def bg(*rgb: int) -> str:
    return _ansi(*rgb, fg=False)


# ── Palette ─────────────────────────────────────────────────────────────────
P: dict[str, tuple[int, int, int]] = {
    "badge_bg":     (124, 58, 237),    # violet
    "badge_fg":     (255, 255, 255),
    "path":         (180, 180, 190),
    "meta":         (120, 120, 130),
    "think":        (196, 181, 253),   # light violet
    "status_bg":    (30, 58, 95),      # dark blue
    "ok":           (74, 222, 128),
    "err":          (248, 113, 113),
    "warn_fg":      (0, 0, 0),
    "warn_bg":      (202, 138, 4),
    "err_bg":       (220, 38, 38),
    "add":          (74, 222, 128),
    "del":          (248, 113, 113),
    "line_no":      (100, 100, 110),
    "prompt":       (200, 200, 210),
    "accent":       (167, 139, 250),
    "todo_done":    (74, 222, 128),
    "todo_open":    (160, 160, 170),
    "tree":         (90, 90, 100),
    "status_fg":    (255, 255, 255),
}


def _rgb(*name: str) -> tuple[int, int, int]:
    return P.get(name[0], (200, 200, 200))


def _hex(r: int, g: int, b: int, fg: bool = True) -> str:
    return _ansi(r, g, b, fg)


# ── Terminal width ──────────────────────────────────────────────────────────
def term_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


# ── Badge pill ──────────────────────────────────────────────────────────────
_BADGE_COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "default": (P["badge_bg"], P["badge_fg"]),
    "warn":    (P["warn_bg"], (0, 0, 0)),
    "err":     (P["err_bg"], (255, 255, 255)),
    "status":  (P["status_bg"], (255, 255, 255)),
    "ok":      ((74, 222, 128), (0, 0, 0)),
}


def badge(label: str, *, color: str = "default") -> str:
    """Rounded pill like ` SHELL ` with background + bold."""
    b, f = _BADGE_COLORS.get(color, _BADGE_COLORS["default"])
    return f"{bg(*b)}{fg(*f)}{_BOLD} {label} {_RESET}"


# ── Dim / reset shortcuts ──────────────────────────────────────────────────
def dim(s: str) -> str:
    return f"{_DIM}{s}{_RESET}"


def strike(s: str) -> str:
    return f"{_STRIKE}{s}{_RESET}"


# ── Thought line ────────────────────────────────────────────────────────────
def think_line(seconds: float | None = None) -> str:
    if seconds is None:
        body = "Thought"
    else:
        sec = max(1, int(round(seconds)))
        unit = "second" if sec == 1 else "seconds"
        body = f"Thought for {sec} {unit}"
    return (
        f"{fg(*P['think'])}* {body} "
        f"{dim('[ctrl+o to expand]')}{_RESET}"
    )


# ── Status chip (Examining / Sculpting) ────────────────────────────────────
def status_chip(verb: str, tokens: str | float | int | None = None) -> str:
    tail = ""
    if tokens is not None:
        if isinstance(tokens, (int, float)):
            if tokens >= 1000:
                tail = f" {tokens / 1000:.1f}k"
            else:
                tail = f" {int(tokens)}"
        else:
            tail = f" {tokens}"
    inner = f" {verb}... "
    return f"{badge(inner.strip(), color='status')}{fg(*P['meta'])}{tail}{_RESET}"


# ── Tool header ────────────────────────────────────────────────────────────
def tool_header(kind: str, detail: str, extra: str = "") -> str:
    """READ  [core/llm.py] 382 lines"""
    parts = [badge(kind), f" {fg(*P['path'])}{detail}{_RESET}"]
    if extra:
        parts.append(f" {fg(*P['meta'])}{extra}{_RESET}")
    return "".join(parts)


# ── Tree helpers ────────────────────────────────────────────────────────────
def tree_prefix() -> str:
    return f"{fg(*P['tree'])}└{_RESET} "


def collapsed(n_lines: int, key_hint: str = "ctrl+o to expand") -> str:
    return f"{tree_prefix()}{dim(f'... +{n_lines} lines [{key_hint}]')}"


# ── Tools → badge map ──────────────────────────────────────────────────────
def map_tool_to_badge(tool_name: str) -> str:
    t = (tool_name or "").lower()
    if "shell" in t or "exec" in t or t == "bash":
        return "SHELL"
    if "read" in t or t in ("read_file", "open_file", "file_system", "file"):
        return "READ"
    if "todo" in t:
        return "TODOS"
    if "write" in t or "edit" in t or "patch" in t or "str_replace" in t or "replace" in t:
        return "EDIT"
    if "search" in t or "web" in t:
        return "SEARCH"
    if "memory" in t:
        return "MEMORY"
    if "kill" in t:
        return "KILL"
    return tool_name.upper()[:12] or "TOOL"


# ── Diff rendering ──────────────────────────────────────────────────────────
def _diff_line(line: str) -> str:
    if line.startswith("+") and not line.startswith("+++"):
        return f"{fg(*P['add'])}{line}{_RESET}"
    if line.startswith("-") and not line.startswith("---"):
        return f"{fg(*P['del'])}{line}{_RESET}"
    return dim(line)


def render_diff(diff_text: str, max_lines: int = 12) -> str:
    if not diff_text:
        return ""
    raw = diff_text.splitlines()
    out: list[str] = []
    for i, line in enumerate(raw[:max_lines]):
        out.append(_diff_line(line))
    if len(raw) > max_lines:
        out.append(collapsed(len(raw) - max_lines))
    return "\n".join(out)


def diff_summary(old: str, new: str) -> tuple[str, str]:
    """Compute unified diff and return (full_diff, summary)."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    adds = sum(1 for l in new_lines if l not in old_lines)
    dels = sum(1 for l in old_lines if l not in new_lines)
    summary = f"Updated with +{adds} -{dels}"
    diff = "\n".join(
        difflib.unified_diff(old_lines, new_lines, lineterm="")
    )
    return diff, summary


# ── TODO block ──────────────────────────────────────────────────────────────
def todo_block(items: list[dict[str, Any]]) -> str:
    """items: [{content, status: done|pending|in_progress}, ...]"""
    head = tool_header("TODOS", f"[{len(items)} items]")
    lines = [head]
    for it in items:
        st = (it.get("status") or "pending").lower()
        text = it.get("content") or it.get("text") or ""
        if st in ("done", "completed", "complete"):
            lines.append(
                f"  {fg(*P['todo_done'])}{strike('☒')} "
                f"{strike(text)}{_RESET}"
            )
        elif st in ("in_progress", "doing"):
            lines.append(
                f"  {fg(*P['accent'])}◐ {text}{_RESET}"
            )
        else:
            lines.append(
                f"  {fg(*P['todo_open'])}☐ {text}{_RESET}"
            )
    return "\n".join(lines)


# ── Other helpers ──────────────────────────────────────────────────────────
def assistant_narration(text: str) -> str:
    return dim(f":: {text}")


def prompt_footer(plan_mode: bool = False) -> str:
    w = term_width()
    line = "─" * max(20, w - 1)
    mode = (
        f"{fg(250, 204, 21)}plan mode{_RESET} {dim('[shift+tab]')}"
        if plan_mode
        else f"{fg(*P['accent'])}» accept edits on{_RESET} {dim('[shift+tab]')}"
    )
    return (
        f"{dim(line)}\n"
        f"{fg(*P['prompt'])}> {_RESET}{dim('Ask your question...')}\n"
        f"{dim(line)}\n"
        f"{mode}\n"
        f"{dim('? for shortcuts')}"
    )
