"""Guard: Batch 5 protocol debt — neon_* palette lives in SEMANTIC, theme.py clean.

verify_protocol.sh flags raw hex in tracked *.py files. Batch 5 moved the six
neon aesthetic colors from ui/theme.py PALETTE into ui/design/theme/semantic.py
(value-stable — same hex, no visual change):
  neon_green #00ff9d, neon_cyan #00fff7, neon_purple #bf5af2,
  neon_pink  #ff2d95, neon_amber #ffcc00, neon_blue #00a8ff

ui/theme.py PALETTE now resolves SEMANTIC.neon_*.hex at import time, so the
source contains no raw hex. The guard pins this: semantic.py must define all
six, and theme.py must reference them via SEMANTIC (not raw hex).
"""

import pathlib
import re

HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")

SEMANTIC_FILE = "ui/design/theme/semantic.py"
THEME_FILE = "ui/theme.py"

NEON_TOKENS = [
    "neon_green",
    "neon_cyan",
    "neon_purple",
    "neon_pink",
    "neon_amber",
    "neon_blue",
]


def test_neon_tokens_defined_in_semantic():
    source = pathlib.Path(SEMANTIC_FILE).read_text()
    for token in NEON_TOKENS:
        assert token in source, f"{token} not defined in {SEMANTIC_FILE}"


def test_theme_py_has_no_raw_hex():
    source = pathlib.Path(THEME_FILE).read_text()
    for lineno, line in enumerate(source.split("\n"), start=1):
        assert not HEX_RE.search(line), (
            f"{THEME_FILE}:{lineno} still contains raw hex: {line.strip()!r}"
        )


def test_theme_py_references_semantic_neon():
    source = pathlib.Path(THEME_FILE).read_text()
    for token in NEON_TOKENS:
        assert f"SEMANTIC.{token}.hex" in source, (
            f"{THEME_FILE} does not reference SEMANTIC.{token}.hex"
        )
