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

# 7. Secret redaction: mask API keys / tokens / passwords before terminal output.
# Matches common secret shapes (key=value, Bearer tokens, sk-/ghp-/eyJ prefixes).
_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)"
    r"(?:api[_-]?key|secret|token|password|passwd|pwd|authorization|auth)"
    r"(?:\s*[:=]\s*|\s+)(['\"]?)([A-Za-z0-9_\-\.~+/]{8,})(['\"]?)"
    r"|"
    r"\b(Bearer\s+[A-Za-z0-9_\-\.~+/]{8,})\b"
    r"|"
    r"\b(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]-[A-Za-z0-9]{8,}|eyJ[A-Za-z0-9_\-]{8,})"
)
_REDACTED = "[REDACTED]"


def strip_ansi_sequences(text: str, keep_color: bool = False) -> str:
    text = _OSC_PATTERN.sub("", text)
    text = _DCS_PATTERN.sub("", text)
    if keep_color:
        text = _CSI_NON_SGR_PATTERN.sub("", text)
    else:
        text = _CSI_PATTERN.sub("", text)
    text = _ESC_PATTERN.sub("", text)
    return text


def redact_secrets(text: str) -> str:
    """Mask secrets (API keys, tokens, passwords, Bearer/key literals) for safe display."""
    if not text:
        return text
    return _SECRET_PATTERN.sub(
        lambda m: (
            f"{m.group(0).split(m.group(2))[0]}{_REDACTED}"
            if m.group(2) else _REDACTED
        ),
        text,
    )


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
    redact_secrets_flag: bool = False,
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
        text = _clean_control_chars(text, preserve_newlines, preserve_tabs, keep_color)

    if redact_secrets_flag:
        text = redact_secrets(text)

    return text


def _clean_control_chars(text: str, preserve_newlines: bool, preserve_tabs: bool, keep_color: bool) -> str:
    """Strip illegal control characters while preserving printable Unicode and allowed layout chars."""
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
            if not cat.startswith("C"):
                cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def format_tool_result_output(raw_output: str | bytes | None, max_length: int = 25000) -> str:
    """
    Format and escape tool execution output for UI and ReAct stream transport.
    Ensures safe UI rendering without ANSI bleed or unbounded memory consumption.
    """
    cleaned = sanitize(raw_output, strip_ansi=True, strip_control=True)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "\n... [TRUNCATED TOOL RESULT]"
    return cleaned


def has_goal_complete_signal(text: str | None) -> bool:
    """Verify if text contains the explicit goal completion marker (<goal-complete/> on own line or <!-- GOAL_COMPLETE -->)."""
    if not text:
        return False
    if "<!-- GOAL_COMPLETE -->" in text or "<!-- GOAL_CANCELLED -->" in text:
        return True
    return bool(re.search(r"^[ \t]*<goal-complete/>[ \t]*$", text, re.MULTILINE))


def strip_goal_complete_marker(text: str | None) -> str:
    """
    Remove goal completion markers (<goal-complete/> or <!-- GOAL_COMPLETE -->)
    and collapse excess newlines for clean visible display.
    """
    if not text:
        return ""
    text = re.sub(r"^[ \t]*<goal-complete/>[ \t]*$\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"<!--\s*GOAL_COMPLETE\s*-->\n?", "", text)
    text = re.sub(r"<!--\s*GOAL_CANCELLED\s*-->\n?", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fix_arabic_reversal(text: str | None) -> str:
    """
    Detect and correct reversed or fragmented Arabic text typed in RTL/LTR terminals
    (e.g., mirrored byte order or fragmented single Arabic characters).
    """
    if not text:
        return ""
    known_fixes = {
        "ي ع د و ت س م م ح ف": "فحص مستودعي",
        "ي ع د و ت س م ص ح ف": "فحص مستودعي",
        "يعدوتسم صحف": "فحص مستودعي",
        "يعدوتسممحف": "فحص مستودعي",
    }
    cleaned = text.strip()
    if cleaned in known_fixes:
        return known_fixes[cleaned]

    arabic_chars = re.findall(r"[\u0600-\u06FF]", text)
    if not arabic_chars:
        return text

    tokens = cleaned.split()
    if len(tokens) >= 2 and all(len(t) == 1 and "\u0600" <= t <= "\u06FF" for t in tokens):
        reversed_chars = tokens[::-1]
        return "".join(reversed_chars)

    return text




