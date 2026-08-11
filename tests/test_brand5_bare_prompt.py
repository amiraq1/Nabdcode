"""BRAND-5: tests for bare-prompt — ❯ only, no label text.

ع1 prompt_starts_with_chevron_only — الـ prompt المرئي يحتوي ❯ في PREFIX أو SUFFIX
                                      بلا نص تسمية قبله
ع2 no_nabd_label                   — PREFIX و SUFFIX لا يحتويان "nabd"
ع3 no_ammar_label                  — PREFIX لا يحتوي "Ammar@NabdOS"
"""
import re
import importlib


def _get_theme():
    mod = importlib.import_module("ui.theme")
    return mod.PROMPT_HTML_PREFIX, mod.PROMPT_HTML_SUFFIX


def _visible(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


# ---------------------------------------------------------------------------
# ع1 — combined prompt (PREFIX + SUFFIX) contains ❯ with no label before it
# ---------------------------------------------------------------------------
def test_prompt_starts_with_chevron_only():
    prefix, suffix = _get_theme()
    combined_visible = _visible(prefix) + _visible(suffix)
    assert "❯" in combined_visible, (
        f"The prompt (PREFIX+SUFFIX) must contain ❯, got: {combined_visible!r}"
    )
    # No word-characters before ❯
    before_chevron = combined_visible.split("❯")[0]
    assert before_chevron.strip() == "", (
        f"No label text should precede ❯ in the prompt, but got: {before_chevron!r}"
    )


# ---------------------------------------------------------------------------
# ع2 — neither PREFIX nor SUFFIX contain "nabd"
# ---------------------------------------------------------------------------
def test_no_nabd_label():
    prefix, suffix = _get_theme()
    assert "nabd" not in prefix, (
        f"PROMPT_HTML_PREFIX must NOT contain 'nabd', got: {prefix!r}"
    )
    assert "nabd" not in suffix, (
        f"PROMPT_HTML_SUFFIX must NOT contain 'nabd', got: {suffix!r}"
    )


# ---------------------------------------------------------------------------
# ع3 — PREFIX must not contain "Ammar@NabdOS" (already removed in BRAND-4)
# ---------------------------------------------------------------------------
def test_no_ammar_label():
    prefix, _ = _get_theme()
    assert "Ammar@NabdOS" not in prefix, (
        f"PROMPT_HTML_PREFIX must NOT contain 'Ammar@NabdOS', got: {prefix!r}"
    )
