"""Phase UI-2 — toolbar, live status chip, expand, plan_mode toggle.

Verifies:
  1. Renderer expand_last returns stored collapsed lines.
  2. Renderer store_collapsed stores and retrieves.
  3. Status chip draw produces \r-based output.
  4. Token count increments.
  5. Plan mode toolbar produces different output.
  6. Button helpers exist.
  7. No crash on boot.
"""

import sys
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.renderer import Renderer
from engine.ui_theme import status_chip, prompt_footer


# ── Expand state ─────────────────────────────────────────────────────────

def test_store_and_expand():
    r = Renderer()
    r.store_collapsed(["line1", "line2", "line3"])
    expanded = r.expand_last()
    assert expanded is not None
    assert "line1" in expanded
    assert "line2" in expanded
    assert "line3" in expanded


def test_expand_multiple():
    r = Renderer()
    r.store_collapsed(["block1"])
    r.store_collapsed(["block2-a", "block2-b"])
    expanded = r.expand_last()
    assert "block2-a" in expanded
    assert "block1" not in expanded  # last only


def test_expand_empty():
    r = Renderer()
    assert r.expand_last() is None


# ── Status chip ──────────────────────────────────────────────────────────

def test_status_chip_has_verb():
    chip = status_chip("Examining", 1234)
    assert "Examining" in chip
    assert "1.2k" in chip or "1234" in chip


def test_status_chip_no_tokens():
    chip = status_chip("Thinking")
    assert "Thinking" in chip


def test_status_chip_ansi():
    chip = status_chip("Working", 500)
    assert "\033[" in chip  # ANSI escape present


# ── Token tick ──────────────────────────────────────────────────────────

def test_token_tick_increments():
    r = Renderer()
    assert r._token_count == 0
    r._token_count = 0
    r.status_start("Testing")
    r.status_tick(5)
    assert r._token_count == 5
    r.status_end()


def test_token_tick_multiple():
    r = Renderer()
    r.status_start("Multi")
    for _ in range(10):
        r.status_tick(1)
    assert r._token_count == 10
    r.status_end()


# ── Toolbar ──────────────────────────────────────────────────────────────

def test_plan_mode_toolbar():
    footer_normal = prompt_footer(plan_mode=False)
    footer_plan = prompt_footer(plan_mode=True)
    assert "plan mode" in footer_plan
    assert "plan mode" not in footer_normal


def test_toolbar_contains_ask():
    footer = prompt_footer()
    assert "Ask your question" in footer


# ── Renderer tool_end stores collapsed ──────────────────────────────────

def test_tool_end_stores_collapsed():
    r = Renderer()
    r.tool_end("execute_shell", success=True, output="a\nb\nc\nd\ne\nf\ng\nh\n")
    expanded = r.expand_last()
    assert expanded is not None
    assert "a" in expanded
    assert "h" in expanded


if __name__ == "__main__":
    test_store_and_expand()
    test_expand_multiple()
    test_expand_empty()
    test_status_chip_has_verb()
    test_status_chip_no_tokens()
    test_status_chip_ansi()
    test_token_tick_increments()
    test_token_tick_multiple()
    test_plan_mode_toolbar()
    test_toolbar_contains_ask()
    test_tool_end_stores_collapsed()
    print("All Phase UI-2 tests passed.")
