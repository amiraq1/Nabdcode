"""Guard: Batch 1 protocol debt — the 5 fixed raw-color sites stay clean.

verify_protocol.sh flags raw hex and ANSI 24-bit escapes in tracked *.py files.
Batch 1 replaced exactly these sites:
  1. main.py: bottom-toolbar ANSI colors (plan mode / accept-edits) → _ansi_fg
     + SEMANTIC rgb tuples.
  2. main.py: prompt HTML fragments (╭─ Ammar@NabdOS, ╰─❯, placeholder) →
     ui.theme PROMPT_HTML_* constants.
  3. ui/repl_termux.py: the HR rule and the same prompt fragments → the same
     ui.theme constants.
  4. nabd_logo.py: "[#555555]" gray → "[grey35]".

The guard pins those replacements by asserting the raw literals no longer
appear ANYWHERE in the three files — the fixed sites AND any accidental
re-introduction. It does NOT require the whole files to be color-free (other
raw colors in repl_termux.py are later batches).
"""

import pathlib
import re

HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")

ANSI_24BIT_RE = re.compile(r"\b(38|48);2;\d+;\d+;\d+")

BATCH1_FILES = [
    "main.py",
    "ui/repl_termux.py",
    "nabd_logo.py",
]

# Raw literals batch 1 removed — asserting their absence pins the fix and
# catches regressions without scanning the rest of the files.
BATCH1_RAW_LITERALS = [
    "#00ff9d",   # main.py prompt prefix / repl_termux prompt
    "#00fff7",   # main.py prompt suffix / repl_termux prompt
    "#555",      # main.py placeholder
    "#555555",   # repl_termux HR rule + nabd_logo gray
]

# The old bottom toolbar used these literal 24-bit escapes.
BATCH1_ANSI_LITERALS = [
    "250;204;21",   # plan mode amber
    "167;139;250",   # accept-edits purple
]


def test_batch1_raw_literals_removed():
    for filepath in BATCH1_FILES:
        source = pathlib.Path(filepath).read_text()
        for literal in BATCH1_RAW_LITERALS:
            assert literal not in source, (
                f"{filepath} still contains removed literal {literal!r}"
            )
        for literal in BATCH1_ANSI_LITERALS:
            assert literal not in source, (
                f"{filepath} still contains removed ANSI literal {literal!r}"
            )


def test_batch1_files_have_no_scan_matching_raw_colors():
    """The batch-1 sites must also be invisible to the official scanner.

    The full-file scan only applies to main.py and nabd_logo.py (fully clean
    after batch 1). repl_termux.py still carries later-batch raw colors, so it
    is exempt here — it is covered by the literal assertions above.
    """
    for filepath in ("main.py", "nabd_logo.py"):
        source = pathlib.Path(filepath).read_text()
        for lineno, line in enumerate(source.split("\n"), start=1):
            assert not HEX_RE.search(line), (
                f"{filepath}:{lineno} still contains raw hex color: {line.strip()!r}"
            )
            assert not ANSI_24BIT_RE.search(line), (
                f"{filepath}:{lineno} still contains raw ANSI color: {line.strip()!r}"
            )
