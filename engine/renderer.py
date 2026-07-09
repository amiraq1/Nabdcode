"""renderer — single owner of terminal output.

Architecture
────────────
EventBus (loop thread)
    │
    ├── think_pulse()   → \r rewrite same line (never \n)
    ├── think_end()     → \r\033[K wipes line entirely
    ├── badge_line()    → real content → \n goes to scrollback
    └── flush()         → atomic commit of buffered _lines

Thread safety
─────────────
All mutable state is protected by a Lock. badge_line / raw / flush / think_*
are safe to call from any thread.
"""

from __future__ import annotations

import itertools
import shutil
import sys
import threading
import time


# ── 5-color ANSI palette ────────────────────────────────────────────────────
_COLORS: dict[str, str] = {
    "cyan":   "\033[36m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "red":    "\033[31m",
    "dim":    "\033[90m",
    "white":  "\033[97m",
    "bg_gray": "\033[48;5;236m",
    "reset":  "\033[0m",
}
_ERASE_LINE = "\r\033[K"
_INDENT = "  "
_STRIKE = "\033[9m"


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

    # ── Core primitive: badge_line ──────────────────────────────────────────

    def badge_line(self, badge: str, message: str, color: str = "cyan") -> None:
        """Single rendering primitive — appends to buffer, goes to scrollback."""
        ansi = _COLORS.get(color, _COLORS["cyan"])
        with self._lock:
            self._lines.append(f"{_INDENT}{ansi}[{badge}]{_COLORS['reset']} {message}")

    def raw(self, text: str = "") -> None:
        """Append a raw unformatted line."""
        with self._lock:
            self._lines.append(text)

    def dim_line(self, message: str) -> None:
        """Dimmed single-line for non-critical background events."""
        with self._lock:
            self._lines.append(f"{_INDENT}{_COLORS['dim']}{message}{_COLORS['reset']}")

    def agent_text(self, text: str = "") -> None:
        """Append an agent response line in distinct white coloring."""
        with self._lock:
            self._lines.append(f"{_INDENT}{_COLORS['white']}{text}{_COLORS['reset']}")

    # ── TODO checklist ─────────────────────────────────────────────────────

    def render_todos(self, items: list) -> None:
        """
        Render the current TODO plan as a compact checklist.
        Uses the same badge_line + color discipline as the rest of the renderer.
        Append-only: each call prints the new state to scrollback.
        """
        with self._lock:
            done_count = sum(1 for i in items if i.status.value == "done")
            header = f"{_COLORS['dim']}TODOS [{done_count}/{len(items)}]{_COLORS['reset']}"
            self._lines.append(header)

            for item in items:
                if item.status.value == "done":
                    box = "☒"
                    color = _COLORS["green"]
                    text = f"{_STRIKE}{item.text}{_COLORS['reset']}"
                elif item.status.value == "in_progress":
                    box = "◐"
                    color = _COLORS["yellow"]
                    text = item.text
                else:
                    box = "☐"
                    color = _COLORS["dim"]
                    text = item.text

                self._lines.append(f"{_INDENT}{color}{box} {text}{_COLORS['reset']}")

    # ── Think (single live line, no \n) ────────────────────────────────────

    def think_start(self, label: str = "thinking") -> None:
        """Begin a single-line THINK indicator. Updates in-place via \\r."""
        with self._lock:
            self._think_alive = True
            self._think_last_draw = 0.0
        self.think_pulse(label)

    def think_pulse(self, label: str = "thinking") -> None:
        """Atomically update the think line. Never issues \\n."""
        with self._lock:
            if not self._think_alive:
                return
            now = time.time()
            if now - self._think_last_draw < self._think_min_interval:
                return
            self._think_last_draw = now
            spin = next(self._spinner)
        # Write outside the lock to avoid holding it during syscall
        sys.stdout.write(
            f"{_ERASE_LINE}{_INDENT}\033[2m[THINK]\033[0m {spin} {label}..."
        )
        sys.stdout.flush()

    def think_end(self) -> None:
        """Wipe the think line from the terminal completely."""
        with self._lock:
            if not self._think_alive:
                return
            self._think_alive = False
        sys.stdout.write(_ERASE_LINE)
        sys.stdout.flush()

    # ── Flush (batched badge + raw lines) ──────────────────────────────────

    def flush(self) -> None:
        """Commit buffered _lines to scrollback atomically."""
        with self._lock:
            if not self._lines:
                return
            lines = self._lines
            self._lines = []
        _update_terminal_size()
        sys.stdout.write(_ERASE_LINE)
        sys.stdout.write("\n".join(lines))
        sys.stdout.write("\n")
        sys.stdout.flush()

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self.think_end()
        self.flush()


# ── Cached terminal size ────────────────────────────────────────────────────
_cached_cols: int = 80

def _update_terminal_size() -> None:
    global _cached_cols
    try:
        _cached_cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    except Exception:
        pass
