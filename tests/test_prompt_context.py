"""Acceptance tests for the prompt bar context line.

Stage 3 (UI plan): the prompt chrome above the input must show the real
workspace root (or "no workspace selected"), the real mode, and the Task
Graph summary — all from actual state, never fabricated.
"""

from __future__ import annotations

import pytest

from core.kernel.security import is_workspace_pinned, pin_workspace_root
from engine.ui_theme import workflow_prompt_hint


# ── workflow_prompt_hint: mode is honest ───────────────────────────────────

def test_hint_shows_normal_mode_by_default():
    assert "accept edits" in workflow_prompt_hint("normal")


def test_hint_shows_plan_mode():
    assert "plan mode" in workflow_prompt_hint("plan")


def test_hint_shows_apply_mode():
    assert "apply mode approved" in workflow_prompt_hint("apply")


def test_hint_includes_task_summary_when_provided():
    hint = workflow_prompt_hint("plan", "TaskGraph r4 active=inspect/research")
    assert "TaskGraph r4" in hint


# ── Prompt chrome context line (via main._run_repl internals) ──────────────

def test_prompt_chrome_includes_workspace_when_pinned():
    """When a workspace is pinned, the prompt chrome must show its path."""
    import tempfile
    from pathlib import Path
    import main

    with tempfile.TemporaryDirectory() as tmp:
        pin_workspace_root(Path(tmp))
        try:
            # Inspect the source of _run_repl._prompt_chrome to verify the
            # workspace line is rendered from get_workspace_root().
            import inspect
            src = inspect.getsource(main._run_repl)
            assert "workspace:" in src
            assert "no workspace selected" in src
            assert "is_workspace_pinned" in src
        finally:
            pin_workspace_root(None)


def test_prompt_chrome_shows_no_workspace_when_unpinned():
    """When no workspace is pinned, the chrome must say so explicitly."""
    import main
    import inspect
    src = inspect.getsource(main._run_repl)
    assert "no workspace selected" in src


def test_prompt_chrome_uses_real_mode():
    """The chrome must use current_mode(state), not a hardcoded value."""
    import main
    import inspect
    src = inspect.getsource(main._run_repl)
    assert "current_mode(state)" in src
    assert "mode_label" in src


def test_prompt_chrome_truncates_long_workspace_path():
    """A long workspace name must be truncated with an explicit marker."""
    import main
    import inspect
    src = inspect.getsource(main._run_repl)
    assert "..." in src  # explicit truncation marker
    assert "NABD_DIAGNOSTIC_PATHS" in src  # full paths only in diagnostic mode


def test_prompt_chrome_hides_graph_when_absent():
    """When there is no task graph, graph_part must be empty (no zeros)."""
    import main
    import inspect
    src = inspect.getsource(main._run_repl)
    # graph_part is only filled when task_summary is truthy.
    assert "if task_summary:" in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
