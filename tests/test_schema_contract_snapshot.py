"""
test_schema_contract_snapshot.py — Schema contract snapshot enforcement.

Every core schema class (EvidenceRecord, TodoItem, WalRecord, etc.) has
its field list snapshotted in ``tests/snapshots/schema_snapshot.json``.
If a field is added, removed, or its type changed, the test FAILS with a
clear message describing exactly what changed.

Updating snapshots:
    python3 tests/_gen_snapshot.py
    (also regenerates the event snapshot)
"""

import json
import dataclasses
import os
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "schema_snapshot.json"


def _load_snapshot():
    with open(SNAPSHOT_PATH) as f:
        return json.load(f)


def _get_schema_fields(cls) -> dict:
    """Return {field_name: {'type': type_str, 'default': repr(default)}}."""
    result = {}
    for f in dataclasses.fields(cls):
        typ = str(f.type.__name__) if hasattr(f.type, "__name__") else str(f.type)
        dflt = f.default
        result[f.name] = {"type": typ, "default": repr(dflt)}
    return result


def _compare_fields(snapshot_key: str, cls, snapshot: dict) -> list[str]:
    """Compare live fields to snapshot. Returns list of differences (empty = pass)."""
    live = _get_schema_fields(cls)
    saved = snapshot.get(snapshot_key, {}).get("fields", {})
    findings = []

    # Fields in live but not in snapshot (added)
    for name in live:
        if name not in saved:
            findings.append(
                f"  [+] NEW field '{name}': type={live[name]['type']}, "
                f"default={live[name]['default']} — snapshot needs update"
            )
    # Fields in snapshot but not in live (removed)
    for name in saved:
        if name not in live:
            findings.append(
                f"  [-] REMOVED field '{name}' (was type={saved[name]['type']})"
            )
    # Fields that changed type
    for name in live:
        if name in saved and live[name]["type"] != saved[name]["type"]:
            findings.append(
                f"  [~] CHANGED field '{name}': "
                f"type {saved[name]['type']} → {live[name]['type']}"
            )

    return findings


# ── Schema classes to monitor ─────────────────────────────────────────

SCHEMA_CLASSES = []

try:
    from core.evidence import EvidenceRecord, VerificationResult
    SCHEMA_CLASSES.append(("EvidenceRecord", EvidenceRecord))
    SCHEMA_CLASSES.append(("VerificationResult", VerificationResult))
except ImportError:
    pass

try:
    from core.todo import TodoItem
    SCHEMA_CLASSES.append(("TodoItem", TodoItem))
except ImportError:
    pass

try:
    from core.convergence_gate import FinalizationDecision, TodoEvidenceLink
    SCHEMA_CLASSES.append(("FinalizationDecision", FinalizationDecision))
    SCHEMA_CLASSES.append(("TodoEvidenceLink", TodoEvidenceLink))
except ImportError:
    pass

try:
    from core.accept_edits_state import WalRecord
    SCHEMA_CLASSES.append(("WalRecord", WalRecord))
except (ImportError, AttributeError):
    pass

try:
    from core.turn_outcome import TurnOutcome
    SCHEMA_CLASSES.append(("TurnOutcome", TurnOutcome))
except (ImportError, AttributeError):
    pass


# ── Tests ─────────────────────────────────────────────────────────────

def test_all_schema_classes_have_snapshot_entries():
    """Every monitored schema class must have a snapshot entry."""
    snapshot = _load_snapshot()
    missing = [name for name, _ in SCHEMA_CLASSES if name not in snapshot]
    # Allow extra entries in snapshot (they may be retired classes)
    assert not missing, (
        f"Schema classes missing from snapshot: {missing}. "
        f"Run 'python3 tests/_gen_snapshot.py' to update."
    )


def test_schema_field_list_unchanged():
    """Field list must match snapshot. Any addition/removal/type-change fails."""
    snapshot = _load_snapshot()
    all_findings = []
    for name, cls in SCHEMA_CLASSES:
        findings = _compare_fields(name, cls, snapshot)
        if findings:
            all_findings.append(f"\n--- {name} ---")
            all_findings.extend(findings)

    if all_findings:
        msg = (
            "Schema contract violation detected.\n"
            "One or more schema classes have changed their field list or types.\n"
            "\n"
            + "\n".join(all_findings) +
            "\n\n"
            "TO UPDATE: python3 tests/_gen_snapshot.py\n"
            "            (runs from tests/ directory; also regenerates event snapshot)\n"
            "After update, commit the new snapshots alongside the schema change."
        )
        assert False, msg
