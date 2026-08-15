"""renderer — single owner of terminal output.

Architecture
────────────
EventBus (loop thread)
    │
    ├── tool_start()    → badge + path line (READ / SHELL / EDIT / …)
    ├── tool_end()      → output block with optional collapse + diff
    ├── thought_start() → * Thought
    ├── thought_end()   → * Thinking …
    ├── stream_chunk()  → live token output (under lock)
    ├── todos()         → TODOS checklist block
    ├── verifier_reject() → yellow VERIFIER badge
    ├── error_badge()   → red ERROR badge
    └── flush()         → atomic commit of buffered _lines

Thread safety
─────────────
All mutable state is protected by a Lock. Every public method acquires
self._lock before reading or writing shared state.
"""

from __future__ import annotations

import difflib
import itertools
import shutil
import sys
import threading
import time
from typing import Any

from core.sanitize import sanitize


# ── 5-color ANSI palette (preserved for backward compat) ────────────────────
_COLORS: dict[str, str] = {
    "cyan":   "\033[36m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "red":    "\033[31m",
    "dim":    "\033[90m",
    "white":  "\033[97m",
    "reset":  "\033[0m",
}
_ERASE_LINE = "\r\033[K"
_INDENT = "  "
_STRIKE = "\033[9m"
_UNSTRIKE = "\033[0m"

# ── UI theme import ─────────────────────────────────────────────────────────
from engine.ui_theme import (
    badge,
    tool_header,
    collapsed,
    render_diff,
    todo_block as ui_todo_block,
    map_tool_to_badge,
    status_chip as ui_status_chip,
    dim,
    fg,
    P,
    tree_prefix,
    status_chip,
)
from ui.design.primitives.personality import style_of
from ui.design.state import UIState

# W-1: the thought line is identified by the ruled Arabic verb, never the
# English word — otherwise thought_end() would not find its own line.
_STYLE = style_of(UIState.THINKING)


# ── Renderer ────────────────────────────────────────────────────────────────
class Renderer:
    """Single owner of terminal output. Append-only, atomic writes. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: list[str] = []
        self._spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        self._think_alive: bool = False
        self._think_last_draw: float = 0.0
        self._think_min_interval: float = 0.12  # ~8 fps throttle
        # UI theme state
        self._think_t0: float | None = None
        self._token_count: int = 0
        # Live status chip (○ Examining... 12.3k)
        self._status_alive: bool = False
        self._status_verb: str = "Examining"
        self._status_last_draw: float = 0.0
        self._status_min_interval: float = 0.15  # ~6 fps throttle
# Expand state
        self._collapsed_data: list[list[str]] = []  # each entry = full output lines
        # Internal buffer for live indicators (thinking/status). These are
        # NEVER flushed to stdout — they are UI-only state captured here so
        # the TUI can read them without leaking to the terminal.
        self._live_buffer: list[str] = []
        # Internal buffer for streamed tokens. Written by stream_chunk(),
        # committed to stdout only by flush(). Prevents mid-stream leakage.
        self._stream_buffer: str = ""

    # ── Legacy methods (preserved for wire_events backward compat) ─────────

    def badge_line(self, badge_txt: str, message: str, color: str = "cyan") -> None:
        """Single rendering primitive — appends to buffer, goes to scrollback."""
        ansi = _COLORS.get(color, _COLORS["cyan"])
        clean = sanitize(message)
        with self._lock:
            self._lines.append(f"{_INDENT}{ansi}[{badge_txt}]{_COLORS['reset']} {clean}")

    def raw(self, text: str = "") -> None:
        """Append a raw unformatted line."""
        clean = sanitize(text)
        with self._lock:
            self._lines.append(clean)

    def dim_line(self, message: str) -> None:
        """Dimmed single-line for non-critical background events."""
        clean = sanitize(message)
        with self._lock:
            self._lines.append(f"{_INDENT}{_COLORS['dim']}{clean}{_COLORS['reset']}")

    def agent_text(self, text: str = "") -> None:
        """Append an agent response line in distinct white coloring."""
        clean = sanitize(text)
        with self._lock:
            self._lines.append(f"{_INDENT}{_COLORS['white']}{clean}{_COLORS['reset']}")

    # ── Legacy TODO checklist (preserved) ──────────────────────────────────

    def render_todos(self, items: list) -> None:
        """
        Render the current TODO plan as a compact checklist.
        Uses the same badge_line + color discipline as the rest of the renderer.
        Each call re-renders the full list (append-only: old list stays in scrollback,
        new state prints below it — no in-place redraw).
        """
        with self._lock:
            done_count = sum(1 for i in items if i.status.value == "done")
            header = f"{_COLORS['dim']}TODOS [{done_count}/{len(items)}]{_COLORS['reset']}"
            self._lines.append(header)

            for item in items:
                if item.status.value == "done":
                    box = "☒"
                    color = _COLORS['green']
                    text = f"{_STRIKE}{item.text}{_UNSTRIKE}" if _STRIKE else item.text
                elif item.status.value == "in_progress":
                    box = "◐"
                    color = _COLORS['yellow']
                    text = item.text
                else:
                    box = "☐"
                    color = _COLORS['dim']
                    text = item.text

                self._lines.append(f"{_INDENT}{color}{box} {text}{_COLORS['reset']}")

    # ── Think (single live line, no \n) ────────────────────────────────────

    def think_start(self, label: str = "thinking") -> None:
        """Begin a single-line THINK indicator. Buffered internally — never written to stdout."""
        with self._lock:
            self._think_alive = True
            self._think_last_draw = 0.0
            self._live_buffer.append(f"[THINK] {label}...")

    def think_pulse(self, label: str = "thinking") -> None:
        """Update the think indicator in the internal buffer. Never writes to stdout."""
        with self._lock:
            if not self._think_alive:
                return
            now = time.time()
            if now - self._think_last_draw < self._think_min_interval:
                return
            self._think_last_draw = now
            spin = next(self._spinner)
            self._live_buffer.append(f"[THINK] {spin} {label}...")

    def think_end(self) -> None:
        """Clear the think indicator from the internal buffer. Never writes to stdout."""
        with self._lock:
            if not self._think_alive:
                return
            self._think_alive = False
            self._live_buffer.clear()

    # ── Flush (batched badge + raw lines) ──────────────────────────────────

    def flush(self) -> None:
        """Commit buffered _lines and _stream_buffer to stdout atomically."""
        with self._lock:
            if not self._lines and not self._stream_buffer:
                return
            lines = self._lines
            self._lines = []
            stream_buf = self._stream_buffer
            self._stream_buffer = ""
        _update_terminal_size()
        sys.stdout.write(_ERASE_LINE)
        if lines:
            sys.stdout.write("\n".join(lines))
            sys.stdout.write("\n")
        if stream_buf:
            sys.stdout.write(stream_buf)
        sys.stdout.flush()

    # ── Stream chunk (progressive token output) ──────────────────────────

    def stream_chunk(self, text: str) -> None:
        """Buffer a token chunk for atomic flush. Never writes to stdout directly.

        Thread-safe: separates kernel I/O from state lock. Tokens are
        accumulated in ``_stream_buffer`` and committed to stdout only when
        ``flush()`` is called, so intermediate reasoning can never leak
        mid-stream.
        """
        clean = sanitize(text, preserve_tabs=True)
        with self._lock:
            self._stream_buffer += clean

    # ══════════════════════════════════════════════════════════════════════
    # Status chip — live \r-based line (○ Examining... 12.3k)
    # ══════════════════════════════════════════════════════════════════════

    def status_start(self, verb: str = "Examining") -> None:
        """Begin a live status chip. Buffered internally — never written to stdout."""
        with self._lock:
            self._status_alive = True
            self._status_verb = verb
            self._token_count = 0
            self._status_last_draw = 0.0
            self._live_buffer.append(f"○ {verb}... 0")

    def status_tick(self, n: int = 1) -> None:
        """Increment token count and update the status chip in the internal buffer."""
        with self._lock:
            self._token_count += n
        self._status_draw()

    def status_snapshot(self, verb: str, tokens: str | float | int | None = None) -> None:
        """Append a read-only terminal status chip to scrollback."""
        self._lines_append(status_chip(verb, tokens))

    def status_end(self) -> None:
        """Clear the status chip from the internal buffer. Never writes to stdout."""
        with self._lock:
            if not self._status_alive:
                return
            self._status_alive = False
            self._live_buffer.clear()

    def _status_draw(self) -> None:
        """Update the status chip in the internal buffer. Never writes to stdout."""
        with self._lock:
            if not self._status_alive:
                return
            now = time.time()
            if now - self._status_last_draw < self._status_min_interval:
                return
            self._status_last_draw = now
            verb = self._status_verb
            count = self._token_count
            chip = ui_status_chip(verb, count)
            self._live_buffer.append(chip)

    # ══════════════════════════════════════════════════════════════════════
    # Expand state — store collapsed output
    # ══════════════════════════════════════════════════════════════════════

    def store_collapsed(self, lines: list[str]) -> None:
        """Store a snapshot of full output lines for expand."""
        with self._lock:
            self._collapsed_data.append(list(lines))
            if len(self._collapsed_data) > 32:
                self._collapsed_data.pop(0)

    def expand_last(self) -> str | None:
        """Return the last stored collapsed block as a plain string, or None."""
        with self._lock:
            if not self._collapsed_data:
                return None
            return "\n".join(self._collapsed_data[-1])

    def tool_start(self, tool: str, args: dict) -> None:
        """Emit a badge + path header at the start of a tool call.

        Matches Cursor style: SHELL [ls -la] or READ [core/llm.py].
        """
        kind = map_tool_to_badge(tool, args)
        detail, extra = _format_args(kind, tool, args or {})
        header = tool_header(kind, detail, extra)
        self._lines_append(header)

    def tool_end(
        self,
        tool: str,
        *,
        success: bool,
        output: str = "",
        summary: str = "",
        diff: str = "",
    ) -> None:
        """Emit tool output — optional summary, diff, or collapsed block.

        If *diff* is provided (EDIT tools), renders a unified diff block.
        If *summary* is provided, emits one tree line.
        Otherwise collapses *output* lines with a folded indicator.
        """
        output = sanitize(output or "", preserve_tabs=True)
        summary = sanitize(summary or "")
        lines = output.splitlines()
        n = len(lines)

        # Diff path
        if diff:
            diff_lines = diff.splitlines()
            adds = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
            dels = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
            stats_line = f"{tree_prefix()}{dim(f'Updated with +{adds} -{dels}')}"
            self._lines_append(stats_line)
            if len(diff_lines) > 16:
                self.store_collapsed(diff_lines)
            rendered = render_diff(diff, max_lines=16)
            if rendered:
                self._lines_append(rendered)
            return

        # Summary path (e.g. "382 lines", "10 results")
        if summary:
            self._lines_append(f"{tree_prefix()}{dim(summary)}")
            return

        # Collapsed output path
        if not lines:
            return
        self.store_collapsed(lines)
        show = lines[:6]
        for l in show:
            self._lines_append(f"{tree_prefix()}{dim(l)}")
        if n > 6:
            self._lines_append(collapsed(n - 6))

    def todos(self, items: list[dict[str, Any]]) -> None:
        """Emit a TODOS checklist block (Cursor style)."""
        block = ui_todo_block(items)
        for l in block.splitlines():
            self._lines_append(l)

    def verifier_reject(self, message: str) -> None:
        """Separator + VERIFIER badge after streamed rejection."""
        self._lines_append("")                              # blank separator
        self._lines_append(
            f"{badge('VERIFIER', color='warn')} {message}"
        )
        self._lines_append(
            f"{badge('VERIFIER', color='warn')} "
            f"{dim('previous streamed text is not accepted')}"
        )

    def error_badge(self, title: str, body: str = "") -> None:
        """Red ERROR badge with optional body."""
        self._lines_append(f"{badge('ERROR', color='err')} {title}")
        if body:
            for l in body.splitlines()[:8]:
                self._lines_append(f"  {dim(l)}")

    def narrate(self, text: str) -> None:
        """Dimmed narration line (:: ...) between tool steps."""
        self._lines_append(f"{dim('::')} {dim(text)}")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _lines_append(self, text: str) -> None:
        """Thread-safe append to the render buffer.  Does NOT auto-flush."""
        with self._lock:
            self._lines.append(text)

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self.think_end()
        self.status_end()
        self.flush()


# ── Cached terminal size ────────────────────────────────────────────────────
_cached_cols: int = 80

def _update_terminal_size() -> None:
    global _cached_cols
    try:
        _cached_cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    except Exception:
        pass


# ── arg formatter (module-level, used by tool_start) ────────────────────────

def _format_args(kind: str, tool: str, args: dict) -> tuple[str, str]:
    """Return (detail, extra) for a tool header.

    e.g. kind=READ  → detail="[core/llm.py]", extra=""
         kind=SHELL → detail="[ls -la]", extra=""
    """
    if kind == "READ":
        path = (
            args.get("path") or args.get("file") or args.get("filename") or tool
        )
        # Extra filled on tool_end with line count
        return f"[{path}]", ""
    if kind == "SHELL":
        cmd = (
            args.get("command") or args.get("cmd") or ""
        )
        cmd = cmd.replace("\n", " ")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        return f"[{cmd}]", ""
    if kind == "EDIT":
        path = (
            args.get("path") or args.get("file") or tool
        )
        return f"[{path}]", ""
    if kind == "TODOS":
        action = args.get("action", "plan")
        item_id = args.get("item_id", "")
        label = f"update #{item_id}" if action == "update" and item_id else action
        return f"[{label}]", ""
    if kind == "TASK":
        role = str(args.get("role", "research")).strip().lower() or "research"
        task_id = str(args.get("task_id", "")).strip()
        prompt = str(args.get("prompt", "")).replace("\n", " ").strip()
        if len(prompt) > 52:
            prompt = prompt[:49] + "..."
        extra = f"node={task_id}" if task_id else "delegated"
        return f"[{role}] {prompt or 'delegated work'}", extra
    if kind in ("SEARCH", "MEMORY", "RAG"):
        query = args.get("query", "")
        return f'["{query[:40]}"]', ""
    return f"[{tool}]", ""

