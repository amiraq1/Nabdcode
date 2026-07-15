"""Live thought compression + high-contrast bento badges for the NABD REPL.

Collapses streaming reasoning into a single dynamic `* Thinking... [Elapsed: Xs]`
line, then freezes it to a compact immutable placeholder while stashing the
raw text in a session dict (expandable via Ctrl+O). Tool actions render as
single-line high-visibility bento badges. All ANSI usage degrades gracefully
when the terminal reports no color support.
"""

from __future__ import annotations

import sys
import time
from typing import Dict, Optional


def _supports_ansi() -> bool:
    """Best-effort: assume ANSI unless stdout is explicitly non-tty/plain."""
    try:
        return sys.stdout.isatty() and os_environ_get("TERM") != "dumb"
    except Exception:
        return False


def os_environ_get(key: str) -> str:
    import os

    return os.environ.get(key, "")


class LiveThoughtCompressor:
    """Manages the live thinking line + raw thought store for one session."""

    def __init__(self) -> None:
        self._active = False
        self._start_ts: float = 0.0
        self._raw: str = ""
        self._last_render_ts: float = 0.0
        self.session_thoughts: Dict[str, str] = {}
        self._step_counter = 0
        self._ansi = _supports_ansi()

    # ── Phase control ──────────────────────────────────────────────────
    def start(self) -> None:
        """Begin a thought phase: capture timestamp, show live line.

        IDEMPOTENT: if a phase is already active (a redundant
        ``thinking_start`` arrived without an intervening ``stop`` — common
        when the model emits the thought prefix twice per turn), just refresh
        the live elapsed line instead of re-spawning. Re-initialising
        ``_start_ts`` here would (a) reset the clock and (b) write a
        *second* ``\\r\\033[K* Thinking...`` line onto a fresh terminal row
        when a prior ``stop()`` already froze the previous phase's line
        above — i.e. the exact "Thinking... stacked 3×" symptom.
        """
        if self._active:
            self._render_live(int(time.time() - self._start_ts))
            return
        self._active = True
        self._start_ts = time.time()
        self._raw = ""
        self._last_render_ts = 0.0
        self._render_live(0)

    def feed(self, text: str) -> None:
        """Buffer raw reasoning into session_thoughts; NEVER print to stdout.

        If the chunk is an [OBS thought] marker or a reasoning token, it is
        accumulated verbatim into the raw store and strictly NOT emitted to
        sys.stdout (no multi-line thought leakage to the terminal).
        """
        if not self._active:
            return
        # Reasoning / thought chunks are buffered only. Detection is explicit
        # but the rule is unconditional: feed() must never write to stdout.
        chunk = text or ""
        self._raw += chunk

    def stop(self) -> Optional[str]:
        """Conclude the phase: erase live line, freeze placeholder, store raw.

        Returns the step id under which the raw thought was stored, or None
        if no phase was active.
        """
        if not self._active:
            return None
        self._active = False
        total_time = max(0, int(time.time() - self._start_ts))
        # Erase the live spinner line entirely, then freeze the clean,
        # immutable placeholder onto its own line (no thought leakage).
        if self._ansi:
            sys.stdout.write(f"\r\033[K\033[2m* Thought for {total_time} seconds [ctrl+o to expand]\033[0m\n")
        else:
            sys.stdout.write(f"* Thought for {total_time} seconds [ctrl+o to expand]\n")
        sys.stdout.flush()
        # Store raw reasoning keyed by a unique step id.
        self._step_counter += 1
        step_id = f"step-{self._step_counter}"
        self.session_thoughts[step_id] = self._raw
        return step_id

    # ── Live line rendering ────────────────────────────────────────────
    def tick(self) -> None:
        """Refresh the elapsed counter on the live line (call periodically)."""
        if not self._active:
            return
        now = time.time()
        # Throttle to ~1s so we don't thrash the terminal.
        if now - self._last_render_ts < 1.0:
            return
        self._last_render_ts = now
        self._render_live(int(now - self._start_ts))

    def _render_live(self, elapsed: int) -> None:
        """Update the single dynamic live line (no implicit newline)."""
        # Strip any trailing newlines so the carriage-return rewrite stays on
        # one line; use the exact primitive write form, never print().
        line = f"* Thinking... [Elapsed: {elapsed}s]".rstrip("\n")
        if self._ansi:
            sys.stdout.write(f"\r\033[K{line}")
        else:
            sys.stdout.write(line)
        sys.stdout.flush()

    def _erase_line(self) -> None:
        if self._ansi:
            sys.stdout.write("\r\033[K")
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()

    def expand(self, step_id: str) -> str:
        """Return the raw thought for a step id (for the Ctrl+O handler)."""
        return self.session_thoughts.get(step_id, "")


# ── High-contrast bento badges ──────────────────────────────────────────
# Color aliases resolved at render time; fall back to plain text if no ANSI.
_BENTO_COLORS = {
    "READ": ("\033[45;30m", "\033[0m"),   # magenta bg, black text
    "SHELL": ("\033[46;30m", "\033[0m"),  # cyan bg, black text
    "WRITE": ("\033[42;30m", "\033[0m"),  # green bg, black text
    "SEARCH": ("\033[44;30m", "\033[0m"), # blue bg, black text
    "AGENT": ("\033[43;30m", "\033[0m"),  # yellow bg, black text
    "DEFAULT": ("\033[47;30m", "\033[0m"),# white bg, black text
}


def _tool_badge_label(tool_name: str) -> str:
    """Map a tool name to a short bento label."""
    name = (tool_name or "").lower()
    if "shell" in name:
        return "SHELL"
    if "reader" in name or "read" in name or "workspace" in name:
        return "READ"
    if "file_system" in name or "write" in name or "edit" in name:
        return "WRITE"
    if "search" in name or "web" in name:
        return "SEARCH"
    if "agent" in name or "executor" in name:
        return "AGENT"
    return "DEFAULT"


def render_bento_badge(tool_name: str, summary: str, ansi: bool = True) -> str:
    """Render a single-line high-contrast bento badge for a tool action.

    Example: ' SHELL  pip install requests' with a cyan background block.
    """
    label = _tool_badge_label(tool_name)
    condensed = _condense(summary)
    if ansi:
        open_code, close_code = _BENTO_COLORS.get(label, _BENTO_COLORS["DEFAULT"])
        return f"{open_code} {label} {close_code} {condensed}"
    return f"[{label}] {condensed}"


def _condense(summary: str) -> str:
    """Condense a tool summary (e.g. a dict args dump) to save vertical space."""
    if summary is None:
        return ""
    text = str(summary)
    # Collapse multi-line / dict dumps into a single tight line.
    text = " ".join(line.strip() for line in text.splitlines() if line.strip())
    text = text.replace("{", "").replace("}", "").replace("'", "")
    if len(text) > 80:
        text = text[:77] + "..."
    return text
