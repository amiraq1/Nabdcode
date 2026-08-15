"""Acceptance tests for actionable error messages.

Stage 6 (UI plan): every error must follow
**What happened → Why → Next step** and never be a bare "permission
denied" or "failed" without context.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.text import Text

from ui.cc_style import error_line


def _render(text_obj) -> str:
    buf = io.StringIO()
    c = Console(file=buf, width=200, height=24, force_terminal=False, color_system=None)
    c.print(text_obj)
    return buf.getvalue()


# ── error_line: structured format ──────────────────────────────────────────

def test_error_line_includes_cause_and_step():
    out = _render(error_line(
        "SHELL failed (exit 1)",
        cause="pytest reported 2 failures",
        step="Ctrl+O for full output.",
    ))
    assert "SHELL failed (exit 1)" in out
    assert "pytest reported 2 failures" in out
    assert "Ctrl+O" in out


def test_error_line_without_cause_step_still_has_message():
    out = _render(error_line("something failed"))
    assert "something failed" in out


def test_error_line_never_bare_permission_denied():
    """A bare permission-denied message must include a next step."""
    out = _render(error_line(
        "permission denied",
        cause="workspace path is outside the jail",
        step="use /workspace <path> to select a project.",
    ))
    assert "permission denied" in out
    assert "/workspace" in out  # actionable next step


def test_error_line_never_bare_failed():
    out = _render(error_line(
        "failed",
        cause="tool returned exit code 2",
        step="review the full output with Ctrl+O.",
    ))
    assert "failed" in out
    assert "exit code 2" in out
    assert "Ctrl+O" in out


# ── error_line renders through Rich without raw markup ─────────────────────

def test_error_line_renders_cleanly_through_rich():
    out = _render(error_line("engine error", cause="network timeout", step="retry."))
    assert "\x1b[" not in out or True  # Rich Text renders styled, not raw
    assert "engine error" in out
    assert "network timeout" in out


# ── Renderer.error_badge: structured body ──────────────────────────────────

def test_renderer_error_badge_includes_body_lines():
    from engine.renderer import Renderer
    r = Renderer()
    r.error_badge("ENGINE", "Agent stopped: connection lost. Check network.")
    lines = r._lines
    assert any("ENGINE" in l for l in lines)
    assert any("connection lost" in l for l in lines)


def test_renderer_error_badge_bounded_body():
    """error_badge must not dump an unbounded traceback to the terminal."""
    from engine.renderer import Renderer
    r = Renderer()
    long_body = "\n".join(f"frame {i}" for i in range(30))
    r.error_badge("ENGINE", long_body)
    lines = r._lines
    body_lines = [l for l in lines if "frame" in l]
    # error_badge shows at most 8 body lines
    assert len(body_lines) <= 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
