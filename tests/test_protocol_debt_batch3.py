"""Guard: Batch 3 protocol debt — scattered raw colors gone from repl_termux.py.

verify_protocol.sh flags raw hex in tracked *.py files. Batch 3 replaced three
scattered raw colors in ui/repl_termux.py:
  - "[#aaaaaa]" (permission ruleset cleared message) → SEMANTIC.text_muted.hex
  - border_style="#1a1a42" (skill executed panel)          → SEMANTIC.border.hex
  - "[#808080]" (thought block divider)                    → SEMANTIC.caption.hex

V-BURY-1 (Am, 2026-08-09): the two replacement SITES that lived inside the
buried dead units — SEMANTIC.text_muted (only in _handle_permission_command)
and SEMANTIC.border (only in _handle_skill_command) — were buried with
run_repl. SEMANTIC.caption survives in the live _display_thought_content.

The guard's core intent is unchanged and now provable MORE strongly: the
file carries ZERO raw hex color literals and every color reference routes
through the semantic palette. The old per-site assertion is re-targeted:
the two tokens that only ever lived in dead code are no longer required to
appear, and the surviving live site (SEMANTIC.caption) still must.
"""

import pathlib

TARGET = "ui/repl_termux.py"

# (raw literal, the SEMANTIC token that replaced it)
BATCH3_SITES = [
    ("#aaaaaa", "SEMANTIC.text_muted"),
    ("#1a1a42", "SEMANTIC.border"),
    ("#808080", "SEMANTIC.caption"),
]


def test_raw_scattered_colors_removed():
    source = pathlib.Path(TARGET).read_text()
    for raw, _ in BATCH3_SITES:
        assert raw not in source, (
            f"{TARGET} still contains raw color literal {raw!r}"
        )


def test_no_raw_hex_color_literals_at_all():
    """V-BURY-1 strengthening: not a single raw #hex color literal remains."""
    import re
    source = pathlib.Path(TARGET).read_text()
    raw_hex = re.findall(r"#[0-9a-fA-F]{6}\b", source)
    assert not raw_hex, (
        f"{TARGET} still contains raw hex color literals: {sorted(set(raw_hex))} — "
        "every color must route through the semantic palette (ui.design.theme.semantic)."
    )


def test_semantic_palette_still_in_use():
    """Every color-bearing site routes through SEMANTIC; the live caption site
    (surviving _display_thought_content) still references SEMANTIC.caption."""
    source = pathlib.Path(TARGET).read_text()
    assert "SEMANTIC.caption" in source, (
        f"{TARGET} must keep referencing SEMANTIC.caption in the live "
        "_display_thought_content divider."
    )


def test_buried_tokens_do_not_resurface():
    """V-BURY-1: SEMANTIC.text_muted and SEMANTIC.border were exclusive to the
    buried dead units (_handle_permission_command / _handle_skill_command).
    They must not resurface in the live file — if a future feature needs a
    muted/border color it must reuse the semantic tokens that still exist."""
    source = pathlib.Path(TARGET).read_text()
    assert "SEMANTIC.text_muted" not in source, (
        "SEMANTIC.text_muted resurfaced in ui/repl_termux.py — it was exclusive "
        "to the buried _handle_permission_command (V-BURY-1)."
    )
    assert "SEMANTIC.border" not in source, (
        "SEMANTIC.border resurfaced in ui/repl_termux.py — it was exclusive "
        "to the buried _handle_skill_command (V-BURY-1)."
    )
