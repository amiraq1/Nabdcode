"""ui_theme.py — Cursor-like TUI theme for Nabdcode (Termux-safe ANSI 256).

Palette, badge pills, tool headers, collapsed blocks, diff rendering,
TODO checklist, thought line, status chip — all stateless helpers.
"""

from __future__ import annotations

import difflib
import shutil
from typing import Any, Optional

from ui.design.theme.semantic import SEMANTIC
from ui.design.icons import Icon
from ui.design.primitives.personality import style_of
from ui.design.state import UIState

# W-1: the waiting line's single source of truth — wired to the design layer.
_STYLE = style_of(UIState.THINKING)

# ── ANSI shortcuts ──────────────────────────────────────────────────────────
# Stage 7: when colors are disabled (NO_COLOR / TERM=dumb), every ANSI
# helper returns a no-op so the output is plain text.  The gate is consulted
# at call time so runtime env changes (e.g. tests) are honored.
try:
    from ui.design.theme import colors_enabled as _colors_enabled
except Exception:  # pragma: no cover — fallback keeps helpers functional
    _colors_enabled = None

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_STRIKE = "\033[9m"


def _color_active() -> bool:
    if _colors_enabled is not None:
        try:
            return _colors_enabled()
        except Exception:
            return True
    return True


def _ansi(r: int, g: int, b: int, fg: bool = True) -> str:
    if not _color_active():
        return ""
    return f"\033[{38 if fg else 48};2;{r};{g};{b}m"


def fg(*rgb: int) -> str:
    return _ansi(*rgb, fg=True)


def bg(*rgb: int) -> str:
    return _ansi(*rgb, fg=False)


# ── Palette ─────────────────────────────────────────────────────────────────
P: dict[str, tuple[int, int, int]] = {
    "badge_bg":     SEMANTIC.action_badge.rgb,
    "badge_fg":     (255, 255, 255),
    "path":         (180, 180, 190),
    "meta":         (120, 120, 130),
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
    "thought":      (216, 180, 254),
    "apply":        (74, 222, 128),
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
    if not _color_active():
        return f" {label} "
    return f"{bg(*b)}{fg(*f)}{_BOLD} {label} {_RESET}"


# ── Dim / reset shortcuts ──────────────────────────────────────────────────
def dim(s: str) -> str:
    if not _color_active():
        return str(s)
    return f"{_DIM}{s}{_RESET}"


def strike(s: str) -> str:
    if not _color_active():
        return str(s)
    return f"{_STRIKE}{s}{_RESET}"


# ── Status chip (Examining / Sculpting) ────────────────────────────────────
def thought_summary(seconds: float | int, *, expand_hint: str = "ctrl+o to expand") -> str:
    """Render a collapsed, privacy-safe thought-duration line."""
    whole_seconds = max(0, int(round(float(seconds))))
    unit = "second" if whole_seconds == 1 else "seconds"
    if not _color_active():
        return f"✳ Thought for {whole_seconds} {unit} [{expand_hint}]"
    return (
        f"{fg(*P['thought'])}✳ Thought for {whole_seconds} {unit}{_RESET} "
        f"{dim(f'[{expand_hint}]')}"
    )


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
    if not _color_active():
        return f"{inner.strip()}{tail}"
    return f"{badge(inner.strip(), color='status')}{fg(*P['meta'])}{tail}{_RESET}"


# ── Tool header ────────────────────────────────────────────────────────────
def tool_header(kind: str, detail: str, extra: str = "") -> str:
    """READ  [core/llm.py] 382 lines"""
    if not _color_active():
        return f"{kind}  {detail}{f' {extra}' if extra else ''}"
    parts = [badge(kind), f" {fg(*P['path'])}{detail}{_RESET}"]
    if extra:
        parts.append(f" {fg(*P['meta'])}{extra}{_RESET}")
    return "".join(parts)


def tool_secondary_info(kind: str, *, success: bool, lines: int = 0,
                        adds: int = 0, dels: int = 0, node: str = "",
                        results: int = 0) -> str:
    """Build the dimmed secondary info line shown under a tool header.

    Returns a plain string like ``382 lines``, ``Updated with +15 −2``,
    ``node=review-1`` or an empty string when there is nothing to show.
    The text is honest — computed from real counts passed in.
    """
    if not success:
        return "failed"
    if kind == "READ" and lines > 0:
        return f"{lines} lines"
    if kind == "EDIT":
        return f"Updated with +{adds} −{dels}"
    if kind == "SHELL" and lines > 0:
        return f"{lines} lines"
    if kind == "TASK":
        return f"node={node}" if node else "delegated"
    if kind in ("SEARCH", "MEMORY", "RAG") and results > 0:
        return f"{results} results"
    if kind == "SCAN" and results > 0:
        return f"{results} entries"
    return ""


# ── Tree helpers ────────────────────────────────────────────────────────────
def tree_prefix() -> str:
    if not _color_active():
        return "└ "
    return f"{fg(*P['tree'])}└{_RESET} "


def collapsed(n_lines: int, key_hint: str = "") -> str:
    if key_hint:
        return f"{tree_prefix()}{dim(f'... +{n_lines} lines [{key_hint}]')}"
    return f"{tree_prefix()}{dim(f'... +{n_lines} lines')}"


# ── Tools → badge map ──────────────────────────────────────────────────────
def map_tool_to_badge(tool_name: str, args: Optional[dict[str, Any]] = None) -> str:
    t = (tool_name or "").lower()
    if t in ("file_system", "file"):
        action = str((args or {}).get("action", "read")).lower()
        if action in ("edit", "write", "append", "replace", "patch"):
            return "EDIT"
        return "READ"
    if "shell" in t or "exec" in t or t == "bash":
        return "SHELL"
    if "read" in t or t in ("read_file", "open_file", "file_system", "file"):
        return "READ"
    if "todo" in t:
        return "TODOS"
    if "write" in t or "edit" in t or "patch" in t or "str_replace" in t or "replace" in t:
        return "EDIT"
    if "rag" in t or "knowledge" in t:
        return "RAG"
    if "search" in t or "web" in t:
        return "SEARCH"
    if "memory" in t:
        return "MEMORY"
    if t in {"repo_scan", "scan"}:
        return "SCAN"
    if t == "task" or "subagent" in t or "delegate" in t:
        return "TASK"
    if "kill" in t:
        return "KILL"
    return tool_name.upper()[:12] or "TOOL"


# ── Stage-aware status verbs ──────────────────────────────────────────────
def select_status_verb(stage: str = "", last_tool: str = "", turn_index: int = 0) -> str:
    """Select a stage-aware verb that reflects what is actually happening.

    No fabricated or alternating verbs — each verb maps to a real action
    category.  ``turn_index`` is accepted for backward-compat callers but
    does not produce a different verb (no alternation).
    """
    s = (stage or "").lower()
    t = (last_tool or "").lower()

    # Plan phase
    if "plan" in s or "choreograph" in s:
        return "Planning"

    # Generating final answer
    if s == "generating" or "answer" in s:
        return "Writing"

    # Tool-specific verbs (checked before stage, as stage may be stale
    # for task/search/rag/memory tools whose _last_stage is never updated).
    if t == "task" or "subagent" in t or "delegate" in t:
        return "Delegating"
    if "search" in t or "web" in t:
        return "Searching"
    if "rag" in t or "knowledge" in t:
        return "Searching"
    if "memory" in t:
        return "Examining"

    # Stage-based verbs for file_system and shell — _last_stage tracks the
    # action type, so stage == "edit" means a write happened.
    if s in ("edit", "write", "replace"):
        return "Editing"
    if s in ("shell", "execute"):
        return "Executing"
    if s in ("read", "inspect"):
        return "Examining"

    # Tool-name fallback for generic detection
    if "shell" in t or "exec" in t or "bash" in t:
        return "Executing"
    if "read" in t or "file" in t:
        return "Examining"

    # First-turn
    if s in ("init", "user_input", "first_turn"):
        return "Reading"

    # No specific stage or tool known
    return "Reasoning"


# ── Diff rendering ──────────────────────────────────────────────────────────
def _diff_line(line: str) -> str:
    if not _color_active():
        return line
    if line.startswith("+") and not line.startswith("+++"):
        return f"{fg(*P['add'])}{line}{_RESET}"
    if line.startswith("-") and not line.startswith("---"):
        return f"{fg(*P['del'])}{line}{_RESET}"
    return dim(line)


def render_diff(diff_text: str, max_lines: int = 16) -> str:
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


def workflow_prompt_hint(mode: str = "normal", task_summary: str = "") -> str:
    """Return a compact, plain-text workflow hint for prompt_toolkit surfaces."""
    normalized = str(mode or "normal").lower()
    if normalized == "apply":
        hint = "apply mode approved  [/review to inspect]"
    elif normalized == "plan":
        hint = "plan mode  [shift+tab]"
    else:
        hint = "» accept edits on  [shift+tab]"
    return f"{hint}\n{task_summary}" if task_summary else hint


def prompt_footer(plan_mode: bool = False, *, apply_mode: bool = False, task_summary: str = "") -> str:
    w = term_width()
    line = "─" * max(20, w - 1)
    if apply_mode:
        mode = f"{fg(*P['apply'])}apply mode approved{_RESET} {dim('[/review to inspect]')}"
    elif plan_mode:
        mode = f"{fg(250, 204, 21)}plan mode{_RESET} {dim('[shift+tab]')}"
    else:
        mode = f"{fg(*P['accent'])}» accept edits on{_RESET} {dim('[shift+tab]')}"
    if task_summary:
        mode = f"{mode}\n{dim(task_summary)}"
    return (
        f"{dim(line)}\n"
        f"{fg(*P['prompt'])}> {_RESET}{dim('Ask your question...')}\n"
        f"{dim(line)}\n"
        f"{mode}\n"
        f"{dim('? for shortcuts')}"
    )
