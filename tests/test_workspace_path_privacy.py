"""Acceptance tests for workspace path-jail validity and path-leak privacy.

Two distinct properties are verified:
  * VALIDITY: tools must never operate outside the pinned workspace.
  * PRIVACY:   the UI must never display unnecessary absolute paths.

The jail decision (``_validate_path`` / FileSystemTool) and the display
decision (``display_path``) are separate: the first authorizes, the second
renders.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from core.kernel.security import (
    display_path,
    is_workspace_pinned,
    pin_workspace_root,
)
from core.sanitize import scrub_absolute_paths


@pytest.fixture
def env(tmp_path):
    """Create project-a/ (workspace) + outside-secret/ (outside) fixtures."""
    proj = tmp_path / "project-a"
    out = tmp_path / "outside-secret"
    (proj / "src").mkdir(parents=True)
    out.mkdir()
    (proj / "src" / "app.py").write_text('print("ok")\n')
    (out / "private.txt").write_text("do-not-display\n")
    pin_workspace_root(proj.resolve())
    yield {"workspace": proj.resolve(), "outside": out.resolve()}
    pin_workspace_root(None)


# ── display_path: in-workspace paths render relative ───────────────────────

def test_display_path_relative_inside_workspace(env):
    ws = env["workspace"]
    assert display_path(str(ws / "src" / "app.py")) == "src/app.py"
    assert display_path("src/app.py") == "src/app.py"
    assert display_path("src/../src/app.py") == "src/app.py"


def test_display_path_root_shows_name_only(env):
    ws = env["workspace"]
    assert display_path(str(ws)) == "project-a"


# ── display_path: outside paths are hidden in normal mode ──────────────────

def test_display_path_abs_outside_hidden(env):
    out = env["outside"]
    assert display_path(str(out / "private.txt")) == "<outside-workspace>"


def test_display_path_abs_outside_diagnostic_reveals(env):
    out = env["outside"]
    assert display_path(str(out / "private.txt"), diagnostic=True) == str(out / "private.txt")


def test_display_path_traversal_hidden(env):
    assert display_path("../outside-secret/private.txt") == "<outside-workspace>"


# ── display_path: windows / UNC never leak in normal mode ──────────────────

def test_display_path_windows_drive_never_leaks(env):
    assert display_path(r"C:\Users\alice\secret\file.txt") == "<path>"


def test_display_path_unc_never_leaks(env):
    assert display_path(r"\\server\share\file.txt") == "<path>"


def test_display_path_windows_diagnostic_reveals(env):
    assert display_path(r"C:\Users\alice\secret\file.txt", diagnostic=True) == r"C:\Users\alice\secret\file.txt"


# ── display_path: no workspace pinned ──────────────────────────────────────

def test_display_path_no_workspace_relative_kept_intact(env):
    """Without a pinned workspace, relative multi-segment paths stay intact."""
    pin_workspace_root(None)
    assert not is_workspace_pinned()
    assert display_path("core/task_graph.py") == "core/task_graph.py"
    assert display_path("src/app.py") == "src/app.py"


def test_display_path_no_workspace_abs_hidden(env):
    """Without a pinned workspace, an absolute path is hidden entirely."""
    pin_workspace_root(None)
    assert not is_workspace_pinned()
    assert display_path("/home/alice/private/secret.txt") == "<outside-workspace>"


def test_display_path_no_workspace_abs_diagnostic_reveals(env):
    """Diagnostic mode reveals the absolute path even without a workspace."""
    pin_workspace_root(None)
    assert not is_workspace_pinned()
    assert display_path("/home/alice/private/secret.txt", diagnostic=True) == "/home/alice/private/secret.txt"


# ── scrub_absolute_paths: shell output privacy ─────────────────────────────

def test_scrub_hides_absolute_paths():
    out = scrub_absolute_paths("pwd\n/home/alice/project/src/app.py")
    assert "<path>" in out
    assert "/home/alice" not in out


def test_scrub_keeps_relative_paths():
    assert scrub_absolute_paths("src/app.py") == "src/app.py"
    assert scrub_absolute_paths("core/task_graph.py") == "core/task_graph.py"


def test_scrub_find_command():
    out = scrub_absolute_paths("find /tmp/nabd-ui-check -maxdepth 2 -type f")
    assert "find <path> -maxdepth 2 -type f" == out
    assert "/tmp/nabd-ui-check" not in out


def test_scrub_empty_and_no_path():
    assert scrub_absolute_paths("") == ""
    assert scrub_absolute_paths("no path here") == "no path here"


# ── Renderer: headers use display_path, output is scrubbed ─────────────────

def test_renderer_header_relativizes_abs_path(env):
    from engine.renderer import _format_args
    ws = env["workspace"]
    detail, _ = _format_args("READ", "file_system",
                             {"path": str(ws / "src" / "app.py")})
    assert "src/app.py" in detail
    assert str(ws) not in detail


def test_renderer_tool_end_scrubs_output_and_expand(env):
    from engine.renderer import Renderer
    ws = env["workspace"]
    r = Renderer()
    r.tool_start("execute_shell", {"command": "find . -type f"})
    r.tool_end("execute_shell", success=True,
               output=f"pwd\n{ws}/src/app.py")
    joined = "\n".join(r._lines)
    assert str(ws) not in joined
    assert "<path>" in joined
    expanded = r.expand_last()
    assert expanded is not None
    assert str(ws) not in expanded  # Ctrl+O must not re-leak
    assert "<path>" in expanded


# ── FileSystemTool jail (validity) ─────────────────────────────────────────

def test_file_system_rejects_traversal(env):
    from tools.file_system import FileSystemTool
    ws = env["workspace"]
    tool = FileSystemTool(workspace=ws)
    res = tool.execute(action="read", path="../outside-secret/private.txt")
    assert not res.success
    # The rejection must not reveal the resolved path.
    assert str(env["outside"]) not in (res.stderr or "")


def test_file_system_rejects_absolute_outside(env):
    from tools.file_system import FileSystemTool
    ws = env["workspace"]
    tool = FileSystemTool(workspace=ws)
    res = tool.execute(action="read", path=str(env["outside"] / "private.txt"))
    assert not res.success
    assert str(env["outside"]) not in (res.stderr or "")


def test_file_system_reads_inside(env):
    from tools.file_system import FileSystemTool
    ws = env["workspace"]
    tool = FileSystemTool(workspace=ws)
    res = tool.execute(action="read", path="src/app.py")
    assert res.success
    assert "print" in res.stdout


def test_file_system_rejects_symlink_escape(env):
    from tools.file_system import FileSystemTool
    ws = env["workspace"]
    link = ws / "evil_link.txt"
    try:
        link.symlink_to(env["outside"] / "private.txt")
    except OSError:
        pytest.skip("symlinks unavailable in this environment")
    try:
        tool = FileSystemTool(workspace=ws)
        res = tool.execute(action="read", path="evil_link.txt")
        assert not res.success
        assert str(env["outside"]) not in (res.stderr or "")
    finally:
        link.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
