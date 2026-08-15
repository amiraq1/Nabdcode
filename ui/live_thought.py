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

from ui.design.theme.semantic import SEMANTIC


def _supports_ansi() -> bool:
    """Best-effort: assume ANSI unless stdout is explicitly non-tty/plain.

    Honors ``NO_COLOR`` and ``TERM=dumb`` via the centralized
    ``colors_enabled()`` gate.
    """
    try:
        from ui.design.theme import colors_enabled
        return colors_enabled()
    except Exception:
        try:
            return sys.stdout.isatty() and os_environ_get("TERM") != "dumb"
        except Exception:
            return False


def os_environ_get(key: str) -> str:
    import os

    return os.environ.get(key, "")


# ── Creative thinking status labels ────────────────────────────────────────
THINKING_STATES: list[tuple[str, str]] = [
    ("★", "Conjuring"),
    ("◇", "Drafting"),
    ("○", "Examining"),
    ("◈", "Synthesizing"),
    ("✦", "Weaving"),
    ("⟡", "Contemplating"),
    ("◉", "Processing"),
    ("⬡", "Reasoning"),
]


def _get_thinking_label(elapsed: int) -> tuple[str, str]:
    """Return (icon, label) that grows more intense as elapsed time increases."""
    if elapsed < 3:
        return ("·", "Thinking")
    if elapsed < 7:
        return ("○", "Examining")
    if elapsed < 15:
        return ("◇", "Contemplating")
    return ("★", "Conjuring")


def _fmt_tokens(n: int) -> str:
    """Format token count for display (e.g. '  ·  47.1k' or '' if zero)."""
    if n == 0:
        return ""
    if n < 1000:
        return f"  ·  {n}"
    return f"  ·  {n/1000:.1f}k"


class LiveThoughtCompressor:
    """Manages the live thinking line + raw thought store for one session."""

    def __init__(self) -> None:
        self._active = False
        self._start_ts: float = 0.0
        self._raw: str = ""
        self._last_render_ts: float = 0.0
        self.session_thoughts: Dict[str, str] = {}
        self._step_counter = 0
        self._token_count: int = 0
        self._ansi = _supports_ansi()
        # UI-CC-2: last concluded thought-phase duration (seconds).
        self.elapsed_seconds: int = 0

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
        self._token_count = 0
        self._last_render_ts = 0.0
        self._render_live(0)

    def add_tokens(self, count: int) -> None:
        """Increment the live token counter shown in the status line."""
        self._token_count += count

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
        # UI-CC-2: expose the duration for the thought indicator.
        self.elapsed_seconds = total_time
        icon, label = _get_thinking_label(total_time)
        token_info = _fmt_tokens(self._token_count)
        # Erase the live line entirely. The frozen thinking placeholder
        # (e.g. "○ Examining... 3s") is NOT written to stdout — only the
        # raw reasoning is stored internally for Ctrl+O expansion.
        # This guarantees no thinking indicator or reasoning text leaks.
        if self._ansi:
            sys.stdout.write("\r\033[K")
        else:
            sys.stdout.write("\n")
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
        """No-op — live thinking line is never written to stdout.

        The Status Bar (AgentStatusBar) is the sole visible indicator of
        agent activity. The live thinking line is buffered internally only.
        """
        pass

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
_badge_rgb = SEMANTIC.action_badge.rgb
_w = SEMANTIC.text_bright.rgb
_badge_open = f"\033[48;2;{_badge_rgb[0]};{_badge_rgb[1]};{_badge_rgb[2]};38;2;{_w[0]};{_w[1]};{_w[2]};1m"
_thinking_rgb = SEMANTIC.thinking.rgb
_thinking_open = f"\033[48;2;{_thinking_rgb[0]};{_thinking_rgb[1]};{_thinking_rgb[2]};38;2;{_w[0]};{_w[1]};{_w[2]};1m"
_BENTO_COLORS: dict[str, tuple[str, str]] = {
    # Unified with map_tool_to_badge labels (single source of truth).
    "READ":    (_badge_open, "\033[0m"),
    "EDIT":    (_badge_open, "\033[0m"),
    "SHELL":   (_badge_open, "\033[0m"),
    "SEARCH":  (_badge_open, "\033[0m"),
    "TODOS":   (_badge_open, "\033[0m"),
    "TASK":    (_thinking_open, "\033[0m"),
    "RAG":     (_badge_open, "\033[0m"),
    "MEMORY":  (_badge_open, "\033[0m"),
    "KILL":    ("\033[48;2;224;62;74m\033[38;2;255;255;255m\033[1m", "\033[0m"),
    "DEFAULT": (_badge_open, "\033[0m"),
}


def _tool_badge_label(tool_name: str, args: dict | None = None) -> str:
    """Map a tool name to a short bento label.

    Delegates to ``map_tool_to_badge`` so that all three rendering paths
    (Renderer, REPL, bento) share one classification source.
    """
    from engine.ui_theme import map_tool_to_badge
    return map_tool_to_badge(tool_name, args)


def render_bento_badge(tool_name: str, summary: str, ansi: bool = True) -> str:
    """Render a single-line high-contrast bento badge for a tool action.

    Example: ' SHELL  pip install requests' with a cyan background block.
    Honors NO_COLOR / TERM=dumb: falls back to plain ``[LABEL] summary``
    when the environment disables color.
    """
    from ui.design.theme import colors_enabled
    ansi = ansi and colors_enabled()
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
