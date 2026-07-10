"""core/sanitize.py — Centralized, production-ready stream and string sanitizer.

Single Source of Truth for stripping ANSI escape sequences, terminal control characters,
OSC/DCS payloads, and illegal control bytes across all subsystem boundaries.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final


# ── Compiled Regular Expressions (Linear O(n), no catastrophic backtracking) ──

# 1. Operating System Command (OSC) sequences: ESC ] ... (BEL | ESC \)
_OSC_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\x1b\][^\a\x1b]*(?:\a|\x1b\\)",
    re.DOTALL,
)

# 2. Device Control String (DCS), Privacy Message (PM), Application Program Command (APC)
_DCS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\x1b[P^_][^\a\x1b]*(?:\a|\x1b\\)",
    re.DOTALL,
)

# 3. Control Sequence Introducer (CSI) sequences: ESC [ ... [a-zA-Z@~]
# Covers colors, cursor movement, erase screen/line, bracketed paste, mouse reporting.
_CSI_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\x1b\[[0-9:;<=>?]*[a-zA-Z@~]",
)
_CSI_NON_SGR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\x1b\[[0-9:;<=>?]*[a-lA-LN-Z@~]",
)

# 4. Single-character ESC sequences / leftover escape codes
_ESC_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\x1b(?:[^\[\]P^_]|$)|\x1b(?=\x1b)|[\x80-\x9a\x9c-\x9f]",
)

# 5. NULL bytes
_NULL_PATTERN: Final[re.Pattern[str]] = re.compile(r"\x00+")

# 6. Backspace, Bell, DEL
_BS_BEL_DEL_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\x07\x08\x7f]")


def strip_ansi_sequences(text: str, keep_color: bool = False) -> str:
    """Strip all ANSI CSI, OSC, DCS, and single escape sequences deterministically."""
    if not text or "\x1b" not in text:
        return text
    text = _OSC_PATTERN.sub("", text)
    text = _DCS_PATTERN.sub("", text)
    if keep_color:
        text = _CSI_NON_SGR_PATTERN.sub("", text)
    else:
        text = _CSI_PATTERN.sub("", text)
    text = _ESC_PATTERN.sub("", text)
    return text


def sanitize(
    text: str | bytes | None,
    *,
    strip_ansi: bool = True,
    normalize_newlines: bool = True,
    strip_null: bool = True,
    strip_control: bool = True,
    preserve_tabs: bool = True,
    preserve_newlines: bool = True,
    keep_color: bool = False,
) -> str:
    """
    Centralized string sanitizer for transport and subsystem boundaries.

    Requirements met:
      • Zero external dependencies
      • Deterministic O(n) linear scanning via pre-compiled regexes
      • Unicode safe (preserves all printable characters and emojis)
      • Configurable ANSI preservation when explicitly requested by renderer
    """
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    elif not isinstance(text, str):
        text = str(text)

    if not text:
        return ""

    # 1. Strip NULL bytes
    if strip_null and "\x00" in text:
        text = _NULL_PATTERN.sub("", text)

    # 2. Strip ANSI escape sequences (CSI, OSC, DCS, ESC)
    if strip_ansi and "\x1b" in text:
        text = strip_ansi_sequences(text, keep_color=keep_color)

    # 3. Strip backspace (0x08), BEL (0x07), DEL (0x7f)
    if strip_control:
        text = _BS_BEL_DEL_PATTERN.sub("", text)

    # 4. Normalize line endings (\r\n -> \n, standalone \r handling)
    if normalize_newlines:
        text = text.replace("\r\n", "\n")
        # Standalone \r should not erase lines when passed through to logs/parsers
        text = text.replace("\r", "\n" if preserve_newlines else "")

    # 5. Strip illegal control characters while preserving printable Unicode
    if strip_control:
        cleaned_chars: list[str] = []
        for ch in text:
            if ch == "\n":
                if preserve_newlines:
                    cleaned_chars.append(ch)
            elif ch == "\t":
                if preserve_tabs:
                    cleaned_chars.append(ch)
            elif ch == "\x1b" and keep_color:
                cleaned_chars.append(ch)
            else:
                cat = unicodedata.category(ch)
                # C = Other (Cc Control, Cf Format, Cs Surrogate, Co Private, Cn Unassigned)
                if not cat.startswith("C"):
                    cleaned_chars.append(ch)
        text = "".join(cleaned_chars)

    return text
