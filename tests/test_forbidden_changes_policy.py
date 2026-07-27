"""
test_forbidden_changes_policy.py — Forbidden changes policy enforcement.

This test enforces that certain structural boundaries are not crossed without
explicit acknowledgement. It does NOT prevent change — it prevents SILENT change.
"""

import ast
import os
from pathlib import Path


# ── Protected files that require policy update before modification ─────
# These files define core schemas, events, or structural contracts.
# Changing them without updating the snapshots/schema_policy.md is forbidden.
PROTECTED_MODULES = {
    "core/evidence.py": "EvidenceRecord, EvidenceLog schema",
    "core/todo.py": "TodoItem, TodoManager schema",
    "core/convergence_gate.py": "FinalizationDecision, CompletionTracker contract",
    "core/kernel/events.py": "Event bus definition",
    "engine/consent.py": "ConsentManager contract",
    "core/_exact_action_contract.py": "Exact-action contract source of truth",
}

# ── Heavy imports that should not be added to core/ without justification ──
# A "heavy import" is something like numpy, torch, transformers, tensorflow, etc.
# The core/ and engine/ packages are intended to be lightweight.
HEAVY_IMPORT_PATTERNS = [
    "numpy", "torch", "tensorflow", "transformers",
    "pandas", "scipy", "sklearn", "cv2", "PIL",
]

# ── Tests ──────────────────────────────────────────────────────────────


def test_protected_modules_not_deleted_or_renamed():
    """Files that define core schemas must still exist."""
    root = Path(__file__).resolve().parent.parent
    missing = []
    for relpath, reason in PROTECTED_MODULES.items():
        full = root / relpath
        if not full.exists():
            missing.append(f"{relpath} ({reason})")
    if missing:
        msg = (
            "Protected schema modules have been deleted or renamed.\n"
            "Each deletion/rename requires an explicit SCHEMA_POLICY.md update:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
        assert False, msg


def test_no_heavy_imports_in_core_or_engine():
    """Core and engine packages must not import heavy ML/data-science libraries.

    Heavy dependencies bloat the installation and increase import time on
    mobile/Termux devices. If a heavy import is genuinely needed, add it to
    the *_HEAVY_IMPORT_PATTERNS allowlist with a justification comment.
    """
    root = Path(__file__).resolve().parent.parent
    findings = []
    for base in ["core", "engine"]:
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
            for pattern in HEAVY_IMPORT_PATTERNS:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.name.split(".")[0]
                            if pattern in name:
                                rel = pyfile.relative_to(root)
                                findings.append(
                                    f"  {rel} imports '{pattern}' "
                                    f"(forbidden by HEAVY_IMPORT_PATTERNS)"
                                )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            name = node.module.split(".")[0]
                            if pattern in name:
                                rel = pyfile.relative_to(root)
                                findings.append(
                                    f"  {rel} imports '{pattern}' "
                                    f"(forbidden by HEAVY_IMPORT_PATTERNS)"
                                )
    if findings:
        msg = (
            "Heavy imports detected in core/ or engine/:\n"
            + "\n".join(findings) +
            "\n\n"
            "If this is intentional, add the pattern to *_HEAVY_IMPORT_PATTERNS "
            "in this test file with a justification comment in the code review."
        )
        assert False, msg


def test_core_evidence_schema_not_renamed():
    """The EvidenceRecord class name must not change."""
    from core.evidence import EvidenceRecord
    assert EvidenceRecord.__name__ == "EvidenceRecord", (
        f"EvidenceRecord was renamed to '{EvidenceRecord.__name__}'. "
        "This is a structural schema change that requires SCHEMA_POLICY.md update."
    )


def test_convergence_gate_function_not_renamed():
    """The can_finalize() function name must not change."""
    from core.convergence_gate import can_finalize
    assert can_finalize.__name__ == "can_finalize", (
        f"can_finalize was renamed to '{can_finalize.__name__}'. "
        "This is a structural contract change."
    )
