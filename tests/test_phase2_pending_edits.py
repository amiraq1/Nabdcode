"""tests/test_phase2_pending_edits.py — Characterization tests for Pending Edits architecture.

V-BURY-1 (Am, 2026-08-09): the dead UI wrapper ``_process_pending_edits``
(which blocked on ``input()`` inside the orphaned async REPL) was buried.
The architectural intent survives unchanged: the REPL must never write files
directly, never touch the pending queue directly, never call drain_pending
itself, and must delegate accept/reject to the canonical API in core. With
the wrapper buried, the guards now assert the canonical home directly:
core/accept_edits_state is the ONLY owner of the pending-edits state machine.
"""

import pytest
import ast
from pathlib import Path
import core.accept_edits_state as _canonical
from core.accept_edits_state import PendingEdit


def test_ui_wrapper_process_pending_edits_is_buried():
    """V-BURY-1: _process_pending_edits must NOT be defined in ui/repl_termux.py."""
    repl_path = Path("ui/repl_termux.py")
    assert repl_path.exists()
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert "_process_pending_edits" not in functions, (
        "_process_pending_edits was buried with run_repl (V-BURY-1) — "
        "the blocking input() prompt machinery must not return to the UI layer."
    )


def test_canonical_api_owns_accept_and_reject():
    """The canonical accept/reject state machine lives in core.accept_edits_state."""
    for attr in ("accept_edit", "reject_edit", "peek_pending", "drain_pending",
                 "has_pending_edits", "PendingEdit", "TransactionOutcome"):
        assert hasattr(_canonical, attr), (
            f"core.accept_edits_state must export {attr} — the canonical "
            "pending-edits API is the only home of accept/reject."
        )


def test_ui_has_no_direct_file_write_path():
    """Target architecture: the UI layer must not call write_text (nothing may
    write files directly outside the canonical API)."""
    repl_path = Path("ui/repl_termux.py")
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)

    has_write_text = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "write_text":
                has_write_text = True
                break

    assert has_write_text is False


def test_ui_does_not_call_drain_pending():
    """Target architecture: drain_pending belongs to core; the UI layer must
    not call it directly."""
    repl_path = Path("ui/repl_termux.py")
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)

    has_drain = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "drain_pending":
                has_drain = True
                break

    assert has_drain is False
