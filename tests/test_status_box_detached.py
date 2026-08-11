"""tests/test_status_box_detached.py — UI-CC-6: status box detached from REPL.

Red-guard tests verifying the REPL no longer renders the AgentStatusBar box,
the compact ✓/▶/○ line is still wired, and the protected file is untouched.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPL = Path(__file__).resolve().parent.parent / "ui" / "repl_termux.py"
STATUS_BAR = Path(__file__).resolve().parent.parent / "ui" / "widgets" / "status_bar.py"


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ── ع1: box_render_call_removed ─────────────────────────────────────────────

def test_box_render_call_removed() -> None:
    """repl_termux.py must not construct or wire AgentStatusBar anymore."""
    source = REPL.read_text(encoding="utf-8")
    assert "AgentStatusBar(" not in source
    assert ".wire()" not in source


# ── ع2: compact_line_still_wired ────────────────────────────────────────────

def test_compact_line_still_wired() -> None:
    """status_compact_line must still be called (replacement feedback)."""
    source = REPL.read_text(encoding="utf-8")
    assert "status_compact_line(" in source


# ── ع3: protected_file_untouched ────────────────────────────────────────────

def test_protected_file_untouched() -> None:
    """ui/widgets/status_bar.py fingerprint must be unchanged."""
    assert _sha16(STATUS_BAR) == "3a829c0a8b17de27"
