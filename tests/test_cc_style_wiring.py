"""tests/test_cc_style_wiring.py — UI-CC-2: wiring cc_style into the visualizer.

Red-guard tests verifying the Claude-Code-style helper functions and that
``ui/repl_termux.py`` actually imports and uses them.
"""

from __future__ import annotations

from pathlib import Path

from ui.cc_style import (
    collapse_lines,
    status_line,
    thought_line,
    tool_header_line,
)

REPL_TERMUX = Path(__file__).resolve().parent.parent / "ui" / "repl_termux.py"


# ── ع1: header_line_read_tool ────────────────────────────────────────────────

def test_header_line_read_tool() -> None:
    header = tool_header_line("file_system.read", {"path": "main.py"})
    assert "READ" in header
    assert "main.py" in header


# ── ع2: header_line_shell_tool ───────────────────────────────────────────────

def test_header_line_shell_tool() -> None:
    header = tool_header_line("execute_shell", {"command": "ls -la"})
    assert "SHELL" in header
    assert "ls -la" in header


# ── ع3: thought_line_format ──────────────────────────────────────────────────

def test_thought_line_format() -> None:
    assert thought_line(1) == "✳ Thought for 1 second [ctrl+o to expand]"
    assert "5 seconds" in thought_line(5)


# ── ع4: status_line_format ───────────────────────────────────────────────────

def test_status_line_format() -> None:
    assert status_line("Drafting", 56700) == "✦ Drafting… 56.7k"


# ── ع5: visualizer_wired_to_cc_style ─────────────────────────────────────────

def test_visualizer_wired_to_cc_style() -> None:
    """repl_termux.py must import cc_style and call the helpers."""
    source = REPL_TERMUX.read_text(encoding="utf-8")
    assert "from ui.cc_style import" in source
    assert "tool_header_line(" in source or "collapse_lines(" in source
