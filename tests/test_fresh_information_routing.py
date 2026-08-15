"""Acceptance tests for temporal / current-information query routing.

Stage 0-C / Stage 3: When the user asks for time-sensitive information
("latest Python", "today's news", "current price"), the system must:

1. Detect the temporal intent (keywords: آخر, أحدث, latest, today, news …).
2. Inject a system message that forces ``web_search`` with an authoritative
   source preference.
3. If ``web_search`` is unavailable, explicitly disclose that live
   verification is not available — never fabricate a stale answer.
4. Non-temporal questions ("ما هو Python؟") must NOT trigger search routing.
"""

from __future__ import annotations

import pytest

from core.temporal_intent import (
    detect_temporal_intent,
    build_temporal_system_message,
    has_temporal_intent,
    TemporalIntent,
)


# ── Intent detection: Arabic ───────────────────────────────────────────────

def test_arabic_latest_version_python_detected():
    intent = detect_temporal_intent("ما هو آخر إصدار من Python؟")
    assert intent is not None
    assert intent.category == "latest"
    assert "python.org" in intent.source_hint


def test_arabic_latest_updates_detected():
    intent = detect_temporal_intent("أريد معرفة آخر تحديثات المشروع")
    assert intent is not None
    assert intent.category == "news"


def test_arabic_current_price_detected():
    intent = detect_temporal_intent("ما هي أسعار الآن؟")
    assert intent is not None
    assert intent.category == "now"


def test_arabic_today_news_detected():
    intent = detect_temporal_intent("ما هي أخبار اليوم؟")
    assert intent is not None


def test_arabic_current_version_detected():
    intent = detect_temporal_intent("الإصدار الحالي للغة Rust")
    assert intent is not None
    assert intent.category == "latest"
    assert "rust-lang.org" in intent.source_hint


# ── Intent detection: English ──────────────────────────────────────────────

def test_english_latest_version_python_detected():
    intent = detect_temporal_intent("What is the latest version of Python?")
    assert intent is not None
    assert intent.category == "latest"
    assert "python.org" in intent.source_hint


def test_english_current_price_detected():
    intent = detect_temporal_intent("What are the current prices today?")
    assert intent is not None
    assert intent.category == "now"


def test_english_news_detected():
    intent = detect_temporal_intent("Latest news and updates")
    assert intent is not None
    assert intent.category == "news"


# ── Non-temporal queries must NOT trigger ──────────────────────────────────

def test_non_temporal_question_not_detected():
    """A general-knowledge question must not trigger temporal routing."""
    intent = detect_temporal_intent("ما هو Python؟")
    assert intent is None


def test_non_temporal_installation_question_not_detected():
    intent = detect_temporal_intent("كيف أثّنت بيئة Python على الجهاز؟")
    assert intent is None


def test_empty_text_not_detected():
    assert detect_temporal_intent("") is None
    assert detect_temporal_intent(None) is None  # type: ignore[arg-type]


def test_has_temporal_intent_boolean():
    assert has_temporal_intent("آخر إصدار") is True
    assert has_temporal_intent("ما هو Python؟") is False


# ── System message content ─────────────────────────────────────────────────

def test_system_message_forces_search_when_available():
    intent = TemporalIntent(category="latest", confidence="high",
                            source_hint="https://python.org/downloads/")
    msg = build_temporal_system_message(intent, has_search_tool=True)
    assert "web_search" in msg
    assert "MUST call" in msg
    assert "python.org" in msg


def test_system_message_discloses_unavailable_when_no_search():
    intent = TemporalIntent(category="latest", confidence="high",
                            source_hint="https://python.org/downloads/")
    msg = build_temporal_system_message(intent, has_search_tool=False)
    assert "NOT available" in msg
    assert "cannot verify" in msg.lower() or "cannot confirm" in msg.lower()
    # Must explicitly prohibit fabrication, not encourage it.
    assert "do not fabricate" in msg.lower() or "must not fabricate" in msg.lower()


def test_system_message_does_not_encourage_stale_facts():
    """The no-search message must explicitly forbid training-data answers."""
    intent = TemporalIntent(category="now", confidence="medium",
                            source_hint="current live source")
    msg = build_temporal_system_message(intent, has_search_tool=False)
    assert "training-data memory" not in msg.lower() or "must not" in msg.lower() or "cannot" in msg.lower()


# ── Integration: source preferences are domain-specific ─────────────────────

@pytest.mark.parametrize("query,expected_domain", [
    ("آخر إصدار Python", "python.org"),
    ("آخر إصدار Rust", "rust-lang.org"),
    ("آخر إصدار Node.js", "nodejs.org"),
    ("آخر إصدار TypeScript", "typescriptlang.org"),
    ("آخر إصدار Git", "git-scm.com"),
])
def test_source_preferences_are_domain_specific(query, expected_domain):
    intent = detect_temporal_intent(query)
    assert intent is not None
    assert intent.category == "latest"
    assert expected_domain in intent.source_hint


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
