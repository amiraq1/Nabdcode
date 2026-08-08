"""Guard: Batch 4 protocol debt — safe theme.py colors use semantic tokens.

verify_protocol.sh flags raw hex in tracked *.py files. Batch 4 replaced four
safe raw colors in ui/theme.py with SEMANTIC tokens:
  - "panel_bg":      "#0d1117" → SEMANTIC.panel.hex       (identical value)
  - "panel_border":  "#30363d" → SEMANTIC.border.hex
  - "prompt_bg":     "#161b22" → SEMANTIC.surface.hex
  - CUSTOM_THEME "white": "#ffffff" → SEMANTIC.text_bright.hex
    (text_bright added to semantic.py as pure white — no visual change)

The guard pins the fix by asserting the raw literals are gone from theme.py
and the replacement sites reference SEMANTIC tokens. The neon_* palette
entries are a separate batch (human decision required) and are not covered.
"""

import pathlib

TARGET = "ui/theme.py"

# (raw literal that was removed, the SEMANTIC token that replaced it)
BATCH4_SITES = [
    ("#0d1117", "SEMANTIC.panel"),
    ("#30363d", "SEMANTIC.border"),
    ("#161b22", "SEMANTIC.surface"),
    ("#ffffff", "SEMANTIC.text_bright"),
]


def test_batch4_raw_colors_removed():
    source = pathlib.Path(TARGET).read_text()
    for raw, _ in BATCH4_SITES:
        assert raw not in source, (
            f"{TARGET} still contains raw color literal {raw!r}"
        )


def test_batch4_replacement_uses_semantic_tokens():
    source = pathlib.Path(TARGET).read_text()
    for _, token in BATCH4_SITES:
        assert token in source, (
            f"{TARGET} does not reference replacement token {token!r}"
        )
