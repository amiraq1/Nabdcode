"""tests/test_cc_style_footer_expand.py — UI-CC-3: bottom-bar hints + expand.

Red-guard tests for ``hint_for_mode`` and ``CollapseStore`` and their
wiring into the REPL.
"""

from __future__ import annotations

from pathlib import Path

from ui.cc_style import CollapseStore, hint_for_mode

MAIN = Path(__file__).resolve().parent.parent / "main.py"
REPL = Path(__file__).resolve().parent.parent / "ui" / "repl_termux.py"


# ── ع1: hint_for_mode_plan ──────────────────────────────────────────────────

def test_hint_for_mode_plan() -> None:
    text, style = hint_for_mode("plan")
    assert "plan mode" in text
    assert "[shift+tab]" in text
    assert style  # non-empty style token


# ── ع2: hint_for_mode_accept ────────────────────────────────────────────────

def test_hint_for_mode_accept() -> None:
    text, style = hint_for_mode("accept")
    assert "accept edits" in text
    assert "[shift+tab]" in text
    assert style


# ── ع3: hint_for_mode_default ───────────────────────────────────────────────

def test_hint_for_mode_default() -> None:
    text, style = hint_for_mode("default")
    assert "? for shortcuts" in text
    assert style


# ── ع4: collapse_store_roundtrip ────────────────────────────────────────────

def test_collapse_store_roundtrip() -> None:
    store = CollapseStore()
    lines = [f"line {i}" for i in range(12)]
    cid = store.store(lines)
    expanded = store.expand(cid)
    assert expanded == lines
    # Unknown id -> None, no crash.
    assert store.expand(999) is None


# ── ع5: footer_and_expand_wired ─────────────────────────────────────────────

def test_footer_and_expand_wired() -> None:
    """BRAND-4: toolbar removed from main.py; hint_for_mode survives in cc_style.

    BRAND-4 deletes the bottom toolbar from main.py, so hint_for_mode is no
    longer called there.  The function must still exist in cc_style as an
    available (unwired) primitive.  /expand and CollapseStore remain in repl.
    """
    from ui.cc_style import hint_for_mode  # must still exist
    assert callable(hint_for_mode), "hint_for_mode must remain callable in cc_style"

    main_src = MAIN.read_text(encoding="utf-8")
    # BRAND-4: hint_for_mode is no longer wired in main.py
    assert "hint_for_mode" not in main_src, (
        "BRAND-4: hint_for_mode must NOT be called in main.py (toolbar removed)"
    )
    assert "/expand" in main_src

    repl_src = REPL.read_text(encoding="utf-8")
    assert "collapse_store" in repl_src
