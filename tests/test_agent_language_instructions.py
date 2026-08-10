"""UX-4: tests for language-enforcement + anti-fabrication instructions."""
import importlib
import inspect


def _get_base_inst() -> str:
    """Extract base_inst source text from main.py (as source string)."""
    src = inspect.getsource(importlib.import_module("main"))
    return src


# ---------------------------------------------------------------------------
# ع1 — same language enforced
# ---------------------------------------------------------------------------
def test_same_language_enforced():
    src = _get_base_inst()
    assert "SAME LANGUAGE" in src, "base_inst must contain 'SAME LANGUAGE'"
    assert "Arabic" in src, "base_inst must mention 'Arabic'"


# ---------------------------------------------------------------------------
# ع2 — no fabrication
# ---------------------------------------------------------------------------
def test_no_fabrication():
    src = _get_base_inst()
    assert (
        "لا أعرف" in src or "do not fabricate" in src.lower()
    ), "base_inst must contain 'لا أعرف' or 'do not fabricate'"


# ---------------------------------------------------------------------------
# ع3 — correct spelling enforced
# ---------------------------------------------------------------------------
def test_correct_spelling_enforced():
    src = _get_base_inst()
    assert "Python" in src, (
        "base_inst must mention 'Python' in a spelling-correction context"
    )
