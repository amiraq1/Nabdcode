"""tests/test_cc_style_compact_panels.py — UI-CC-5: compact CC-style panels.

Red-guard tests verifying the compact header/status/error builders return
rich ``Text`` (not Panels) and that the REPL wires them in.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from ui.cc_style import final_answer_header, status_compact_line, error_line

REPL = Path(__file__).resolve().parent.parent / "ui" / "repl_termux.py"


# ── ع1: final_answer_header_format ──────────────────────────────────────────

def test_final_answer_header_format() -> None:
    header = final_answer_header()
    assert isinstance(header, Text)
    assert "FINAL ANSWER" in header.plain
    assert "◆" in header.plain
    # It must NOT be a Panel (no frame).
    assert not hasattr(header, "box")


# ── ع2: status_compact_line_format ──────────────────────────────────────────

def test_status_compact_line_format() -> None:
    # All three done → all ✓, no ▶.
    line = status_compact_line(
        step=1, elapsed=42.8,
        thinking=True, tools=True, generating=True,
    )
    assert isinstance(line, Text)
    plain = line.plain
    assert "Step 1" in plain
    assert "42.8" in plain
    assert "✓" in plain  # done markers

    # Tools active (Thinking done, Generating pending) → ▶ appears.
    active = status_compact_line(
        step=2, elapsed=3.0,
        thinking=True, tools=False, generating=False,
    )
    assert "▶" in active.plain


# ── ع3: error_line_format ───────────────────────────────────────────────────

def test_error_line_format() -> None:
    line = error_line("boom")
    assert isinstance(line, Text)
    assert "✖" in line.plain
    assert "ERROR" in line.plain
    assert "boom" in line.plain


# ── ع4: repl_wired_compact ──────────────────────────────────────────────────

def test_repl_wired_compact() -> None:
    source = REPL.read_text(encoding="utf-8")
    assert "final_answer_header(" in source
    assert "status_compact_line(" in source
    assert "error_line(" in source
