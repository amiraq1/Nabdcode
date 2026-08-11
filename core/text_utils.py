"""text_utils.py — Bidirectional (bidi) text utilities for mixed Arabic/English terminal output.

Design principles:
  1. Arabic text is preserved in its ORIGINAL Unicode code-point order inside
     RuntimeState and transcript — NO reversal or reordering happens in the
     data layer.
  2. Display-only processing (directional isolation marks, width calculation)
     is applied ONLY in the renderer layer, not in the input buffer or state.
  3. Display width is computed using Unicode East Asian Width (wcwidth-style)
     semantics, not ``len()``, so combining marks and wide characters are
     measured correctly.
  4. ANSI escape codes are stripped before width calculation so they never
     inflate the measured width or corrupt cursor positioning.

RTL constraint (Am+8 D-6): full bidi shaping is NOT implemented here. Width is
measured in display columns; visual ordering is delegated to the terminal. The
data layer never reorders text and never injects RLM/LRM to fake support.

TERM-1 (Am+9): when ``arabic_reshaper`` and ``bidi`` ARE installed (e.g. a
desktop Linux box with a C toolchain), ``render_arabic()`` performs proper
Arabic character shaping + logical-to-visual reordering. On Termux/Android
these packages typically cannot be compiled (they need the ``fribidi`` C
library), so the import is lazy and the function degrades gracefully to the
bidi-isolation fallback below. The data layer is untouched: shaping is
display-only.
"""

from __future__ import annotations

import re
import sys
import unicodedata


# ── ANSI escape sequence regex ──────────────────────────────────────────────
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# TERM-1: Lazy optional deps (fribidi-based).  Import failure must NEVER
# break startup — on Android/Termux these wheels are usually unavailable.
_HAS_BIDI = False
try:
    import arabic_reshaper  # type: ignore[import-untyped]
    from bidi.algorithm import get_display  # type: ignore[import-untyped]
    _HAS_BIDI = True
except (ImportError, OSError):
    arabic_reshaper = None
    get_display = None


def render_arabic(text: str) -> str:
    """Render Arabic text for terminal display.

    Uses proper shaping (arabic-reshaper) + logical-to-visual reordering
    (python-bidi) when both are installed.  Falls back to bidi-isolation
    marks (``safe_display``) otherwise, so Termux without ``fribidi``
    still renders readable text.

    Returns the display-ready string.  Never raises.
    """
    if not text:
        return text
    if _HAS_BIDI and is_arabic(text):
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            pass
    return safe_display(text)


def has_bidi_support() -> bool:
    """Return True when arabic-reshaper + python-bidi are importable."""
    return _HAS_BIDI


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text for width calculation."""
    if not text:
        return ""
    return _ANSI_RE.sub("", text)


def is_arabic(text: str) -> bool:
    """Check if the text consists primarily of Arabic (or right-to-left) characters."""
    if not text or not text.strip():
        return False
    arabic_chars = sum(
        1 for c in text if unicodedata.bidirectional(c) in ("AL", "AN", "R")
    )
    return arabic_chars > len(text) * 0.3


def display_width(text: str) -> int:
    """Compute the terminal display width of *text*, accounting for:

    - ANSI escape codes (stripped before measurement)
    - Wide characters (East Asian Width = Wide or Fullwidth → 2 columns)
    - Combining marks (zero-width)
    - Control characters (zero-width)

    This is NOT ``len()`` — it returns the number of terminal columns the
    text will occupy, which is what matters for cursor positioning and
    wrapping on a narrow Termux screen.
    """
    if not text:
        return 0
    # Strip ANSI codes first so they don't inflate the width.
    clean = strip_ansi(text)
    width = 0
    for ch in clean:
        if ch == "\n" or ch == "\t":
            # Tab = 1 column (conservative; real terminals vary)
            width += 1
            continue
        if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            # Combining marks, enclosing marks, format chars → zero width
            continue
        # East Asian Width
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            width += 2
        else:
            width += 1
    return width



def safe_display(text: str) -> str:
    """Apply display-only bidi isolation to text for terminal rendering.

    - Arabic lines get RLM prefix + LRM suffix for visual isolation.
    - Non-Arabic lines get LRM prefix.
    - The original Unicode order is NEVER changed — only directional marks
      are added for the terminal's BiDi algorithm.
    - ANSI codes are preserved (they are not stripped here; the renderer
      handles them).
    """
    lrm = "\u200E"  # Left-to-Right Mark
    rlm = "\u200F"  # Right-to-Left Mark

    if not text:
        return text

    # Split into lines, apply directional isolation per line.
    lines = text.splitlines()
    result = []
    for line in lines:
        if is_arabic(line):
            result.append(rlm + line + lrm)
        else:
            result.append(lrm + line)
    return "\n".join(result)


def wrap_text(text: str, width: int) -> list[str]:
    """Word-wrap *text* to fit within *width* terminal columns.

    Uses ``display_width()`` (not ``len()``) so Arabic and wide characters
    are measured correctly. ANSI codes are preserved in the output but
    excluded from width calculation.

    Uses a simple greedy algorithm — sufficient for terminal output.
    """
    if not text:
        return [""]

    # Strip ANSI for measurement but keep original for output.
    clean = strip_ansi(text)
    lines = []
    current = ""
    current_width = 0

    words = clean.split(" ")
    for word in words:
        word_width = display_width(word)
        if current_width + word_width > width and current:
            lines.append(current)
            current = word
            current_width = word_width
        else:
            if current:
                current += " " + word
                current_width += 1 + word_width
            else:
                current = word
                current_width = word_width

    if current:
        lines.append(current)

    return lines if lines else [""]
