"""tests/test_inline_status_panel_removed.py — UI-CC-7: inline panel removed.

Red-guard tests verifying the live SectionPanel box is no longer rendered
from the REPL/one-shot wiring, the compact line is printed instead, and the
protected file stays untouched.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPL = ROOT / "ui" / "repl_termux.py"
MAIN = ROOT / "main.py"
STATUS_BAR = ROOT / "ui" / "widgets" / "status_bar.py"


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ── ع1: no_inline_running_tools_panel ───────────────────────────────────────

def test_no_inline_running_tools_panel() -> None:
    """The live SectionPanel box must not be rendered from the REPL/one-shot path.

    The protected status_bar.py may still *define* the panel, but the
    consumer (main.py wire_events / repl_termux render_agent_events) must
    not invoke start()/stop() anymore — only wire() (listening) is allowed.
    Without start(), _live stays None and _update_live() is a no-op, so the
    box never actually renders; the compact line is the visual feedback.
    """
    main_src = MAIN.read_text(encoding="utf-8")
    assert "status_bar.start()" not in main_src
    assert "status_bar.stop()" not in main_src

    repl_src = REPL.read_text(encoding="utf-8")
    assert "AgentStatusBar(" not in repl_src


# ── ع2: compact_line_printed_on_step ────────────────────────────────────────

def test_compact_line_printed_on_step() -> None:
    """status_compact_line must be called and its output printed in the
    step-start and step-end handlers in main.py."""
    src = MAIN.read_text(encoding="utf-8")
    assert "status_compact_line(" in src
    assert "Console().print(status_compact_line(" in src


# ── ع3: protected_untouched ─────────────────────────────────────────────────

def test_protected_untouched() -> None:
    """The three protected fingerprints must be unchanged."""
    assert _sha16(STATUS_BAR) == "42b5c014b36d6c18"
    assert _sha16(ROOT / "tests" / "test_the_bar_hears_the_bus.py") == "bf47735d30e0e1c6"
    assert _sha16(ROOT / "tests" / "test_the_bar_clock_turns.py") == "8bbc623c388d4f02"
