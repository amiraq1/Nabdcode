#!/usr/bin/env python3
"""
tests/test_exe07_complexity_reduction.py — Complexity Reduction & Architecture Tests
=====================================================================================
Validates EXE-07 requirements:
  1. High cyclomatic complexity functions in core/accept_edits_state.py are decomposed.
  2. accept_edit cyclomatic complexity is reduced from 68 to <= 12.
  3. Decomposed helpers maintain strict transaction integrity and failure safety.
"""

from __future__ import annotations

import ast
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import core.accept_edits_state as _state
from core.accept_edits_state import (
    PendingEdit,
    TransactionOutcome,
    TransactionResult,
    _accept_edits_pending,
    _file_digest,
    _state_lock,
    accept_edit,
    load_workspace_identity,
    reset_session,
    set_journal_path,
    set_mode,
)


def _compute_ast_cyclomatic_complexity(node: ast.AST) -> int:
    """Compute standard McCabe cyclomatic complexity on an AST node."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.If,
                ast.For,
                ast.While,
                ast.AsyncFor,
                ast.AsyncWith,
                ast.ExceptHandler,
                ast.With,
                ast.Assert,
            ),
        ):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, ast.IfExp):
            complexity += 1
    return complexity


class TestComplexityReduction(unittest.TestCase):
    """Test suite for validating cyclomatic complexity bounds and decomposed behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nabd_exe07_test_")
        self.ws_dir = os.path.join(self.tmpdir, "workspace")
        os.makedirs(self.ws_dir, exist_ok=True)
        self.journal_path = os.path.join(self.ws_dir, ".nabd", "journal", "journal.jsonl")

        reset_session()
        load_workspace_identity(self.ws_dir)
        set_journal_path(self.journal_path)
        set_mode(True)

    def tearDown(self):
        reset_session()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_accept_edit_cyclomatic_complexity_bounds(self):
        """accept_edit() cyclomatic complexity must be <= 12 (reduced from 68)."""
        source_path = Path("core/accept_edits_state.py")
        self.assertTrue(source_path.exists())

        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        func_complexities = {}

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_complexities[node.name] = _compute_ast_cyclomatic_complexity(node)

        self.assertIn("accept_edit", func_complexities)
        accept_edit_cc = func_complexities["accept_edit"]
        self.assertLessEqual(
            accept_edit_cc,
            12,
            f"accept_edit complexity is {accept_edit_cc}, expected <= 12",
        )

        # Also check decomposed helpers have low bounded complexity
        for helper in (
            "_claim_edit_for_accept",
            "_check_edit_preconditions",
            "_record_prepared_wal",
        ):
            self.assertIn(helper, func_complexities)
            self.assertLessEqual(
                func_complexities[helper],
                10,
                f"{helper} complexity is {func_complexities[helper]}, expected <= 10",
            )

    def test_decomposed_accept_edit_happy_path(self):
        """accept_edit successfully applies change and emits journal events."""
        target_file = Path(self.ws_dir) / "hello.py"
        target_file.write_text("print('old')\n", encoding="utf-8")
        orig_digest = _file_digest(str(target_file))

        edit = PendingEdit(
            edit_id="edit-happy-1",
            path="hello.py",
            resolved_path=str(target_file),
            old_content="print('old')\n",
            new_content="print('new world')\n",
            diff="-print('old')\n+print('new world')\n",
            additions=1,
            removals=1,
            expected_original_digest=orig_digest,
            status="PENDING",
            version=1,
        )
        with _state_lock:
            _accept_edits_pending.append(edit)

        result = accept_edit("edit-happy-1", expected_version=1)
        self.assertIn(
            result.outcome,
            (TransactionOutcome.ACCEPTED, TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING),
        )
        self.assertEqual(result.succeeded_ids, ["edit-happy-1"])
        self.assertEqual(target_file.read_text(encoding="utf-8"), "print('new world')\n")

    def test_decomposed_accept_edit_conflict_path(self):
        """accept_edit returns CONFLICT if on-disk content doesn't match expected digest."""
        target_file = Path(self.ws_dir) / "conflict.py"
        target_file.write_text("actual on-disk content\n", encoding="utf-8")

        edit = PendingEdit(
            edit_id="edit-conflict-1",
            path="conflict.py",
            resolved_path=str(target_file),
            old_content="old content\n",
            new_content="brand new content\n",
            diff="-old content\n+brand new content\n",
            additions=1,
            removals=1,
            expected_original_digest="wrong_digest_value",
            status="PENDING",
            version=1,
        )
        with _state_lock:
            _accept_edits_pending.append(edit)

        result = accept_edit("edit-conflict-1", expected_version=1)
        self.assertEqual(result.outcome, TransactionOutcome.CONFLICT)
        self.assertEqual(result.succeeded_ids, [])
        # Content on disk must NOT be modified
        self.assertEqual(target_file.read_text(encoding="utf-8"), "actual on-disk content\n")


if __name__ == "__main__":
    unittest.main()
