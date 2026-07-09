"""renderer — single owner of terminal output.

Architecture
────────────
EventBus (loop thread)
    │
    ▼
Renderer.append() ──→ buffer: list[str]
    │
    ▼ (flush at event boundaries)
Renderer.flush() ──→ sys.stdout.write()

No background threads. No competing writers.
"""

from __future__ import annotations

import shutil
import sys


SPINNER_FRAMES: tuple[str, ...] = (
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"
)

# ── 5-color ANSI palette ────────────────────────────────────────────────────
_COLORS: dict[str, str] = {
    "cyan":   "\033[36m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "red":    "\033[31m",
    "dim":    "\033[90m",
}
_RESET = "\033[0m"
_INDENT = "  "


# ── Cached terminal size ────────────────────────────────────────────────────
_cached_cols: int = 80


def _update_terminal_size() -> None:
    global _cached_cols
    try:
        _cached_cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    except Exception:
        pass


# ── Renderer ────────────────────────────────────────────────────────────────
class Renderer:
    """Single owner of terminal output. Append-only, atomic writes."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._spinner_idx: int = 0
        self._spinner_active: bool = False

    # ── Core primitive: badge_line ──────────────────────────────────────────

    def badge_line(self, badge: str, message: str, color: str = "cyan") -> None:
        """
        Single rendering primitive.

        badge   – 4-6 char uppercase label (EXEC, READ, WRITE, SEARCH, MODEL, ERROR, DONE)
        message – human-readable single-line summary
        color   – cyan | green | yellow | red | dim
        """
        ansi = _COLORS.get(color, _COLORS["cyan"])
        self._lines.append(f"{_INDENT}{ansi}[{badge}]{_RESET} {message}")

    def dim_line(self, message: str) -> None:
        """Dimmed single-line for non-critical background events."""
        self._lines.append(f"{_INDENT}{_COLORS['dim']}{message}{_RESET}")

    def raw(self, text: str = "") -> None:
        """Append a raw unformatted line."""
        self._lines.append(text)

    def stream_start(self, prefix: str = "❯ AGENT: ") -> None:
        """Start token-by-token live streaming after stopping any active spinner."""
        self.spinner_stop()
        sys.stdout.write(f"\r\033[K{_COLORS['green']}{prefix}{_RESET}")
        sys.stdout.flush()

    def stream_token(self, token: str) -> None:
        """Write a single token immediately to stdout during live streaming."""
        sys.stdout.write(token)
        sys.stdout.flush()

    def stream_end(self) -> None:
        """Finish live streaming with a clean newline."""
        sys.stdout.write("\n")
        sys.stdout.flush()

    def flush(self) -> None:
        """
        Atomically write buffered lines to stdout.

        Three cases:
          1. Spinner only (no _lines) → \\r rewrites same line, no \\n.
             Cursor stays ON the spinner line for the next overwrite.
          2. Content only (no spinner) → \\r\\033[K clears any remnant,
             then content + \\n.  Cursor moves to a fresh line below.
          3. Content + spinner          → \\r\\033[K + content + \\n + spinner.
             Content goes to scrollback; spinner lives on the current line.
        """
        _update_terminal_size()

        spinner_line = self._spinner_line() if self._spinner_active else None

        if spinner_line and not self._lines:
            # Pure spinner update — overwrite same terminal line
            sys.stdout.write(f"\r{spinner_line}")
            sys.stdout.flush()
            return

        if not self._lines:
            return

        # Real content (with or without trailing spinner)
        sys.stdout.write("\r\033[K")
        sys.stdout.write("\n".join(self._lines))
        if spinner_line:
            # Spinner stays on current line (no \\n) so subsequent
            # pure-spinner updates overwrite it with \\r
            sys.stdout.write("\n")
            sys.stdout.write(spinner_line)
        else:
            # No trailing spinner — move cursor to fresh line
            sys.stdout.write("\n")
        sys.stdout.flush()
        self._lines.clear()

    # ── Spinner ─────────────────────────────────────────────────────────────

    def spinner_start(self) -> None:
        self._spinner_active = True
        self._spinner_idx = 0

    def spinner_stop(self) -> None:
        if self._spinner_active:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        self._spinner_active = False

    def _spinner_line(self) -> str | None:
        if not self._spinner_active:
            return None
        frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
        self._spinner_idx += 1
        return f"{_INDENT}{frame} Thinking..."

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self.spinner_stop()
        self.flush()
