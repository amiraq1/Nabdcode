"""Acceptance tests for the tool header secondary info line.

Stage 4 (UI plan): after a tool header, a dimmed secondary line shows the
real outcome — line counts for reads/shell, diff stats for edits, node id
for tasks.  The line must be honest (computed from real data), never
fabricated.
"""

from __future__ import annotations

import pytest

from engine.renderer import Renderer
from engine.ui_theme import tool_secondary_info


# ── tool_secondary_info: pure function ─────────────────────────────────────

def test_read_secondary_shows_line_count():
    assert tool_secondary_info("READ", success=True, lines=382) == "382 lines"


def test_read_secondary_empty_when_no_lines():
    assert tool_secondary_info("READ", success=True, lines=0) == ""


def test_edit_secondary_shows_diff_stats():
    assert tool_secondary_info("EDIT", success=True, adds=15, dels=2) == "Updated with +15 −2"


def test_shell_secondary_shows_line_count():
    assert tool_secondary_info("SHELL", success=True, lines=7) == "7 lines"


def test_task_secondary_shows_node():
    assert tool_secondary_info("TASK", success=True, node="review-1") == "node=review-1"


def test_task_secondary_shows_delegated_when_no_node():
    assert tool_secondary_info("TASK", success=True, node="") == "delegated"


def test_search_secondary_shows_result_count():
    assert tool_secondary_info("SEARCH", success=True, results=5) == "5 results"


def test_failed_tool_secondary_shows_failed():
    assert tool_secondary_info("READ", success=False, lines=10) == "failed"


def test_unknown_kind_returns_empty():
    assert tool_secondary_info("UNKNOWN", success=True, lines=3) == ""


# ── Renderer.tool_end: secondary line is emitted ───────────────────────────

def test_renderer_emits_secondary_line_for_read():
    renderer = Renderer()
    renderer.tool_start("file_system", {"action": "read", "path": "core/x.py"})
    renderer.tool_end(
        "file_system", success=True,
        output="line1\nline2\nline3",
    )
    lines = renderer._lines
    # Header line + secondary "3 lines" + collapsed/summary content
    assert any("3 lines" in l for l in lines), f"Missing secondary line: {lines}"


def test_renderer_emits_secondary_line_for_edit_diff():
    renderer = Renderer()
    renderer.tool_start("file_system", {"action": "write", "path": "engine/y.py"})
    renderer.tool_end(
        "file_system", success=True,
        output="changed",
        diff="--- a/engine/y.py\n+++ b/engine/y.py\n@@ -1 +1 @@\n-old\n+new",
    )
    lines = renderer._lines
    # The diff stats line is rendered as "Updated with +1 -1" (ASCII)
    assert any("Updated with +1 -1" in l for l in lines), f"Missing diff stats: {lines}"


def test_renderer_no_secondary_for_failed_tool():
    renderer = Renderer()
    renderer.tool_start("file_system", {"action": "read", "path": "core/x.py"})
    renderer.tool_end("file_system", success=False, output="error")
    lines = renderer._lines
    assert any("failed" in l for l in lines), f"Missing failed marker: {lines}"


def test_renderer_secondary_line_is_dimmed():
    """The secondary line must use the dim style (not plain).

    When NO_COLOR is set, the line must be plain (semantically equivalent);
    when colors are enabled it must carry the dim ANSI code.
    """
    from ui.design.theme import colors_enabled
    renderer = Renderer()
    renderer.tool_start("file_system", {"action": "read", "path": "core/x.py"})
    renderer.tool_end("file_system", success=True, output="a\nb\nc")
    lines = renderer._lines
    sec = next((l for l in lines if "3 lines" in l), "")
    if colors_enabled():
        assert "\033[2m" in sec or "dim" in sec.lower(), f"Secondary not dimmed: {sec!r}"
    else:
        assert "\x1b[" not in sec, f"ANSI in NO_COLOR mode: {sec!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
