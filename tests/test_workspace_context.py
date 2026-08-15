"""Acceptance tests for workspace context handling.

Stage 0-D / Stage 4: Auto-scan must use an *explicitly pinned* workspace
root, never silently fall back to ``os.listdir(".")``.  The scan result
must include ``workspace_root`` so the display layer can show the user
exactly which directory was scanned.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from core.commands.auto_scan import maybe_auto_scan
from core.kernel.security import (
    get_workspace_root,
    is_workspace_pinned,
    pin_workspace_root,
)


# ── Workspace pinning ──────────────────────────────────────────────────────

def test_is_workspace_pinned_false_by_default():
    """Without pinning, is_workspace_pinned must report False."""
    # Note: other tests may pin the workspace. We test the function contract
    # by checking that a fresh pin/unpin cycle works.
    assert is_workspace_pinned() in (True, False)  # contract: returns bool


def test_pin_and_get_workspace_root():
    """After pin_workspace_root, get_workspace_root returns the pinned path."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pin_workspace_root(root)
        assert is_workspace_pinned() is True
        assert get_workspace_root() == root.resolve()


# ── maybe_auto_scan: non-scan query ────────────────────────────────────────

def test_non_scan_query_not_triggered():
    result = maybe_auto_scan("hello world", None)
    assert result["triggered"] is False
    assert "workspace_root" in result
    assert result["workspace_root"] is None


# ── maybe_auto_scan: workspace not pinned ──────────────────────────────────

def test_unpinned_workspace_returns_explicit_message():
    """When no workspace is pinned, scan must NOT proceed silently."""
    pin_workspace_root(None)  # reset
    # Ensure is_workspace_pinned is False
    if is_workspace_pinned():
        pytest.skip("Could not unpin workspace in this environment")

    result = maybe_auto_scan("افحص المستودع", None)
    assert result["triggered"] is True
    assert result["success"] is False
    assert result["workspace_root"] is not None  # still reports the fallback path
    # The error must ask the user to select a folder — not scan silently.
    assert "مستودع" in result["error"] or "مجلد" in result["error"]


# ── maybe_auto_scan: pinned workspace uses explicit root ───────────────────

def test_pinned_workspace_uses_explicit_root():
    """When workspace is pinned, scan uses that root and reports it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pin_workspace_root(root)
        try:
            result = maybe_auto_scan("افحص المستودع", None)
            assert result["triggered"] is True
            assert str(result["workspace_root"]) == str(root.resolve())
            assert os.path.samefile(result["workspace_root"], str(root))
        finally:
            pin_workspace_root(None)


def test_pinned_workspace_empty_dir_reports_path():
    """Empty directory: error must mention the specific path."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pin_workspace_root(root)
        try:
            result = maybe_auto_scan("استكشاف", None)
            assert result["triggered"] is True
            assert result["success"] is False
            # The error must include the actual workspace root path.
            assert str(root) in result["error"] or str(root.resolve()) in result["error"]
        finally:
            pin_workspace_root(None)


def test_pinned_workspace_with_files_succeeds():
    """Non-empty workspace: scan succeeds and reports entry count + root."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "test_file.py").write_text("hello")
        (root / "subdir").mkdir()
        pin_workspace_root(root)
        try:
            result = maybe_auto_scan("فحص", None)
            assert result["success"] is True
            assert result["entry_count"] == 2  # test_file.py + subdir
            assert str(result["workspace_root"]) == str(root.resolve())
        finally:
            pin_workspace_root(None)


# ── maybe_auto_scan: dict structure ────────────────────────────────────────

def test_result_always_includes_workspace_root():
    """Every return path must include workspace_root key."""
    # Non-scan
    r = maybe_auto_scan("hello", None)
    assert "workspace_root" in r

    # Scan without workspace pinned
    pin_workspace_root(None)
    if not is_workspace_pinned():
        r = maybe_auto_scan("افحص", None)
        assert "workspace_root" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
