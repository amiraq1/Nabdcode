"""Tests for the pre-write snapshot engine (enables /undo)."""

from __future__ import annotations

import pytest
from pathlib import Path

from core.snapshot import SnapshotEngine


def test_save_and_undo_roundtrip() -> None:
    """save() preserves the original; undo() restores it after a modification."""
    import tempfile

    td = Path(tempfile.mkdtemp())
    snap = SnapshotEngine(workspace_root=td)
    f = td / "x.py"
    f.write_text("original")
    snap.save("x.py")
    f.write_text("modified")
    assert f.read_text() == "modified"
    msg = snap.undo("x.py")
    assert f.read_text() == "original"
    assert "Restored" in msg


def test_new_file_noop() -> None:
    """save() on a non-existent path is a silent no-op (no crash, no snapshot)."""
    snap = SnapshotEngine(workspace_root=Path("/tmp"))
    snap.save("does_not_exist.py")  # must not raise
    assert snap.undo("does_not_exist.py") == "No snapshot for 'does_not_exist.py'"


def test_undo_without_snapshot() -> None:
    """undo() on a never-snapshotted existing file reports no snapshot."""
    import tempfile

    td = Path(tempfile.mkdtemp())
    snap = SnapshotEngine(workspace_root=td)
    f = td / "y.py"
    f.write_text("data")
    assert snap.undo("y.py") == "No snapshot for 'y.py'"
