"""tests/test_api_key_normalization.py — Am+9: API key prefix normalization.

Root-cause regression guard: OpenRouter keys are case-sensitive; a pasted
``Sk-or-v1-...`` (capital S) is rejected with HTTP 401, silently
accumulating provider failures until the whole router enters cooldown.
``_normalize_api_key`` must canonicalize the prefix to lowercase
``sk-or-v1-...`` before the key is used.
"""

from __future__ import annotations

from core.llm import _normalize_api_key


class TestApiKeyNormalization:
    def test_capital_s_normalized(self):
        """Sk-or-v1-... is normalized to sk-or-v1-... (root cause fix)."""
        assert _normalize_api_key("Sk-or-v1-abc123") == "sk-or-v1-abc123"

    def test_uppercase_prefix_normalized(self):
        """SK-OR-V1-... is normalized to sk-or-v1-..."""
        assert _normalize_api_key("SK-OR-V1-abc123") == "sk-or-v1-abc123"

    def test_canonical_key_unchanged(self):
        """A correct sk-or-v1-... key passes through unchanged."""
        key = "sk-or-v1-TEST-NOT-A-REAL-SECRET-abcdef"
        assert _normalize_api_key(key) == key

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is removed."""
        assert _normalize_api_key("  sk-or-v1-x  ") == "sk-or-v1-x"

    def test_empty_key_unchanged(self):
        """Empty string returns empty string."""
        assert _normalize_api_key("") == ""

    def test_non_string_passthrough(self):
        """Non-string inputs pass through unchanged (defensive)."""
        assert _normalize_api_key(None) is None
        assert _normalize_api_key(12345) == 12345

    def test_preserves_remainder(self):
        """The remainder after the prefix is preserved byte-for-byte."""
        original = "Sk-or-v1-THE-REMAINDER-IS-UNTOUCHED"
        result = _normalize_api_key(original)
        assert result == "sk-or-v1-THE-REMAINDER-IS-UNTOUCHED"
