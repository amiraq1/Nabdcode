"""Guard: Batch 3 protocol debt — scattered raw colors gone from repl_termux.py.

verify_protocol.sh flags raw hex in tracked *.py files. Batch 3 replaced three
scattered raw colors in ui/repl_termux.py:
  - "[#aaaaaa]" (permission ruleset cleared message) → SEMANTIC.text_muted.hex
  - border_style="#1a1a42" (skill executed panel)          → SEMANTIC.border.hex
  - "[#808080]" (thought block divider)                    → SEMANTIC.caption.hex

The guard pins the fix by asserting the raw literals are absent from the file
and the replacement sites reference SEMANTIC tokens. It checks content, not
line numbers (line numbers shift as the file evolves).
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


def test_replacement_uses_semantic_tokens():
    source = pathlib.Path(TARGET).read_text()
    for _, token in BATCH3_SITES:
        assert token in source, (
            f"{TARGET} does not reference replacement token {token!r}"
        )
