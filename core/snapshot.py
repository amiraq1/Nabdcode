"""Snapshot engine — pre-write file backup with /undo stack."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

SNAPSHOT_DIR = ".nabd/snapshots"


class SnapshotEngine:
    """Saves pre-write copies, restores on /undo."""

    def __init__(self, workspace_root: Path) -> None:
        self._root = Path(workspace_root)
        self._stack: dict[str, list[Path]] = {}  # relpath → [snapshot_paths]

    def save(self, relpath: str) -> None:
        """Copy file to .nabd/snapshots/<ts>/<relpath> if file exists."""
        if not relpath:
            return
        full = self._root / relpath
        if not full.exists() or not full.is_file():
            return
        ts = str(int(time.time()))
        dst = self._root / SNAPSHOT_DIR / ts / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full, dst)
        self._stack.setdefault(relpath, []).append(dst)

    def undo(self, relpath: str) -> str:
        """Restore most recent snapshot. Return status message."""
        snaps = self._stack.get(relpath, [])
        if not snaps:
            return f"No snapshot for '{relpath}'"
        latest = snaps.pop()
        full = self._root / relpath
        full.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(latest, full)
        return f"Restored '{relpath}' from snapshot {latest.parent.name}"
