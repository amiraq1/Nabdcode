"""
test_event_contract_policy.py — Event bus contract snapshot enforcement.

All bus.emit() event names in engine/, core/, tools/ are snapshotted in
``tests/snapshots/event_snapshot.json``. Adding a new event without updating
the snapshot causes a test failure.

Updating:
    python3 tests/_gen_snapshot.py
"""

import json
import os
import re
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "event_snapshot.json"


def _discover_all_events() -> set[str]:
    """Scan engine/, core/, tools/ for bus.emit() calls."""
    events = set()
    root = Path(__file__).resolve().parent.parent  # project root
    for base in ["engine", "core", "tools"]:
        dirpath = root / base
        if not dirpath.exists():
            continue
        for pyfile in dirpath.rglob("*.py"):
            if "__pycache__" in str(pyfile):
                continue
            try:
                text = pyfile.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in re.finditer(r'bus\.emit\(["\']([^"\']+)["\']', text):
                events.add(m.group(1))
    return events


def _load_event_snapshot() -> set[str]:
    with open(SNAPSHOT_PATH) as f:
        return set(json.load(f))


def test_event_names_match_snapshot():
    """All bus.emit() event names must match the approved snapshot."""
    live = _discover_all_events()
    saved = _load_event_snapshot()

    added = live - saved
    removed = saved - live

    findings = []
    if added:
        findings.append(f"  [+] NEW events (not in snapshot): {sorted(added)}")
    if removed:
        findings.append(f"  [-] REMOVED events (in snapshot, no longer in code): {sorted(removed)}")

    if findings:
        msg = (
            "Event contract violation.\n"
            + "\n".join(findings) +
            "\n\n"
            "TO UPDATE: python3 tests/_gen_snapshot.py\n"
            "If the new event is intentional, commit the updated snapshot alongside it."
        )
        assert False, msg
