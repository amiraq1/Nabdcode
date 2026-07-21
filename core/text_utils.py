"""text_utils.py — Bidirectional (bidi) text utilities for mixed Arabic/English terminal output."""

from __future__ import annotations

import unicodedata


def is_arabic(text: str) -> bool:
    """Check if the text consists primarily of Arabic (or right-to-left) characters."""
    if not text or not text.strip():
        return False
    arabic_chars = sum(
        1 for c in text if unicodedata.bidirectional(c) in ("AL", "AN", "R")
    )
    return arabic_chars > len(text) * 0.3


def safe_display(text: str) -> str:
    """Isolate Arabic and RTL text lines using explicit directional marks (LRM/RLM) to prevent terminal bidi distortion."""
    lrm = "\u200E"  # Left-to-Right Mark
    rlm = "\u200F"  # Right-to-Left Mark

    lines = text.splitlines()
    result = []
    for line in lines:
        if is_arabic(line):
            result.append(rlm + line + lrm)
        else:
            result.append(lrm + line)
    return "\n".join(result)
