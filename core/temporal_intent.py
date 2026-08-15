"""
temporal_intent.py — Detect time-sensitive / current-information queries.

When a user asks about the *latest*, *current*, or *recent* state of
something (e.g. "ما هو آخر إصدار من Python؟"), the LLM must not answer
from static training-data memory.  This module provides:

- ``detect_temporal_intent()`` — classify a user query into a temporal
  category (or None if no temporal intent is detected).
- ``build_temporal_system_message()`` — produce a system message that
  instructs the LLM to route the query through ``web_search`` with a
  preferred authoritative source.

Design: the detector is keyword-based (not ML) so it works offline and
has no dependencies.  Every keyword is verifiable in source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── Keyword lists (Arabic + English) ────────────────────────────────────────

# Verbs / phrases that ask for the *latest* state of something.
_LATEST_KEYWORDS: tuple[str, ...] = (
    "آخر",        # last / latest
    "أحدث",       # newest
    "اخير",       # last (variant)
    "latest",
    "newest",
    "most recent",
    "current version",
    "الإصدار الحالي",
    "آخر إصدار",
    "version actuelle",  # French, common in search
)

# Phrases that ask for *today's* / *now* state.
_NOW_KEYWORDS: tuple[str, ...] = (
    "اليوم",      # today
    "حالياً",      # currently
    "now",
    "today",
    "currently",
    "current price",
    "أسعار",      # prices
    "price",
)

# Phrases that ask for *news* / *updates* (time-bound info).
_NEWS_KEYWORDS: tuple[str, ...] = (
    "أخبار",      # news
    "تحديثات",    # updates
    "updates",
    "news",
    "آخر تحديقات",
)

_ALL_TEMPORAL_KEYWORDS: tuple[str, ...] = (
    _LATEST_KEYWORDS + _NOW_KEYWORDS + _NEWS_KEYWORDS
)


@dataclass(frozen=True)
class TemporalIntent:
    """Classification result for a temporal query."""

    category: str  # "latest" | "now" | "news"
    confidence: str  # "high" | "medium"
    source_hint: str  # preferred authoritative URL / domain


# ── Source map: which domain to prefer for each category ────────────────────

def _source_for(category: str, text: str) -> str:
    """Return the preferred authoritative source URL for *category*."""
    lowered = text.lower()
    if category == "latest":
        # Language-specific / project-specific source preferences.
        if "python" in lowered or "بايثون" in lowered:
            return "https://python.org/downloads/"
        if "rust" in lowered or "رست" in lowered:
            return "https://www.rust-lang.org/"
        if "node" in lowered or "نود" in lowered:
            return "https://nodejs.org/"
        if "typescript" in lowered:
            return "https://www.typescriptlang.org/"
        if "git" in lowered:
            return "https://git-scm.com/"
        # Generic — prefer official docs / Wikipedia latest.
        return "official documentation"
    if category == "now":
        if "price" in lowered or "سعر" in lowered or "أسعار" in lowered:
            return "https://www.example.com/pricing"
        return "current live source"
    if category == "news":
        return "https://en.wikipedia.org/wiki/Main_Page"
    return "official source"


def detect_temporal_intent(text: str) -> Optional[TemporalIntent]:
    """Classify *text* into a temporal category.

    Returns a ``TemporalIntent`` if the query asks for time-sensitive
    information, or ``None`` if no temporal keywords are detected.

    Detection is keyword-based: if any temporal keyword appears in the
    (case-folded) text, the query is classified.  Confidence is "high"
    when at least two temporal keywords match, "medium" otherwise.
    """
    if not text:
        return None

    folded = " ".join(text.split()).lower()  # normalize whitespace + case

    # Arabic text in user input is typically not lowercased by str.lower(),
    # but str.casefold() handles Arabic case folding.  Check both.
    folded_ar = text  # raw for Arabic substring checks

    matched_categories: list[str] = []

    for kw in _LATEST_KEYWORDS:
        if kw.lower() in folded or kw in folded_ar:
            matched_categories.append("latest")
            break

    for kw in _NOW_KEYWORDS:
        if kw.lower() in folded or kw in folded_ar:
            matched_categories.append("now")
            break

    for kw in _NEWS_KEYWORDS:
        if kw.lower() in folded or kw in folded_ar:
            matched_categories.append("news")
            break

    if not matched_categories:
        return None

    # Priority: news > latest > now.
    # Rationale: "آخر تحديقات" (latest updates) is fundamentally a news/updates
    # intent even though "آخر" alone would be "latest".  News-specific keywords
    # (أخبار, تحديقات, news, updates) take precedence when present.
    if "news" in matched_categories:
        category = "news"
    elif "latest" in matched_categories:
        category = "latest"
    else:
        category = "now"

    confidence = "high" if len(matched_categories) >= 2 else "medium"
    return TemporalIntent(
        category=category,
        confidence=confidence,
        source_hint=_source_for(category, text),
    )


def build_temporal_system_message(intent: TemporalIntent, has_search_tool: bool = True) -> str:
    """Produce a system message that forces live-search routing.

    Args:
        intent: The detected temporal intent.
        has_search_tool: Whether ``web_search`` is registered/available.

    Returns:
        A system message string to inject before the LLM turn.  When
        *has_search_tool* is False the message explicitly tells the LLM
        to disclose that live verification is unavailable — it must NOT
        fabricate a stale answer.
    """
    source = intent.source_hint

    if has_search_tool:
        return (
            "[TEMPORAL QUERY DETECTED] The user is asking for current or "
            "time-sensitive information. You MUST call `web_search` to verify "
            f"the latest information BEFORE answering. Prefer the authoritative "
            f"source: {source}. Do not answer from training-data memory alone. "
            "After obtaining search results, cite the source and date."
        )
    return (
        "[TEMPORAL QUERY DETECTED] The user is asking for current or "
        "time-sensitive information. The `web_search` tool is NOT available "
        "in this session. You MUST explicitly state that live verification "
        f"is unavailable and cannot confirm the latest information from {source}. "
        "Do not fabricate a version number, date, or price from memory. "
        "State: \"I cannot verify the current information because live web "
        "search is not available.\" and suggest the user enable network access."
    )


def has_temporal_intent(text: str) -> bool:
    """Convenience: True if *text* contains temporal keywords."""
    return detect_temporal_intent(text) is not None
