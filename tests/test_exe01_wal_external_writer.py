#!/usr/bin/env python3
"""
tests/test_exe01_wal_external_writer.py — WAL Contract & External Writer Safety Tests
=====================================================================================
Validates EXE-01 requirements:
  1. Formal WAL State progression: PREPARED -> APPLIED -> COMMITTED -> RESOLVED.
  2. External modification before precondition check -> CONFLICT.
  3. Verification mismatch / corrupted write -> CONFLICT/RECONCILIATION/FAILED,
     and APPLIED is NOT falsely recorded.
  4. Failure after side effect but before journal write -> RECONCILIATION_REQUIRED.
  5. Deterministic journal replay and recovery report.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import core.accept_edits_state as _state
from core.accept_edits_state import (
    PendingEdit,
    TransactionOutcome,
    WalRecord,
    accept_edit,
    load_and_reconcile_journal,
    load_workspace_identity,
    reset_session,
    set_journal_path,
    set_mode,
)


class TestWalExternalWriterSafety(unittest.TestCase):
    """Test suite for WAL invariants under external concurrent writers."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nabd_wal_test_")
        self.workspace = os.path.join(self.tmpdir, "workspace")
        os.makedirs(self.workspace, exist_ok=True)
        self.journal_path = os.path.join(self.workspace, ".nabd", "journal", "journal.jsonl")

        reset_session()
        load_workspace_identity(self.workspace)
        set_journal_path(self.journal_path)
        set_mode(True)

    def tearDown(self):
        reset_session()
        _state._pre_replace_test_hook = None
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_pending_edit(self, rel_path: str, old_content: str, new_content: str) -> PendingEdit:
        resolved = os.path.join(self.workspace, rel_path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(old_content)
        orig_digest = _state._compute_digest(old_content)
        edit = PendingEdit(
            path=rel_path,
            resolved_path=resolved,
            old_content=old_content,
            new_content=new_content,
            diff=f"-{old_content}\n+{new_content}",
            additions=1,
            removals=1,
            expected_original_digest=orig_digest,
        )
        with _state._state_lock:
            _state._accept_edits_pending.append(edit)
        return edit

    def test_external_writer_before_precondition_yields_conflict(self):
        """If an external process changes the file before accept_edit runs, CONFLICT is returned."""
        edit = self._create_pending_edit("main.py", "original_content", "agent_content")

        # External modification occurs before accept_edit
        with open(edit.resolved_path, "w", encoding="utf-8") as f:
            f.write("external_modification_pre")

        res = accept_edit(edit.edit_id)

        self.assertEqual(res.outcome, TransactionOutcome.CONFLICT)
        with open(edit.resolved_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "external_modification_pre")

    def test_digest_verification_mismatch_prevents_applied_journal_record(self):
        """If target digest mismatches expected content after write (e.g. concurrent overwrite),
        WAL invariant ensures APPLIED is NOT emitted, and failure/reconciliation is triggered."""
        edit = self._create_pending_edit("data.txt", "v1_content", "v2_agent_content")
        target_path = Path(edit.resolved_path)

        # Mock digest computation during verification to simulate an unexpected file state / corruption
        real_file_digest = _state._file_digest
        call_count = [0]

        def corrupting_file_digest(path: str) -> str:
            call_count[0] += 1
            # Return real digest for precondition checks (1 and 2), but mismatch on post-write verify (call >= 3)
            if call_count[0] >= 3:
                return "corrupted_or_concurrently_modified_digest"
            return real_file_digest(path)

        _state._file_digest = corrupting_file_digest
        try:
            res = accept_edit(edit.edit_id)

            self.assertIn(
                res.outcome,
                (TransactionOutcome.FAILED, TransactionOutcome.RECONCILIATION_REQUIRED),
            )

            # Read journal records to ensure no successful APPLIED event was emitted
            records = []
            if os.path.exists(self.journal_path):
                with open(self.journal_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line))

            applied_events = [r for r in records if r.get("event_type") == "APPLIED"]
            self.assertEqual(len(applied_events), 0, "Must not emit successful APPLIED on verification mismatch")
        finally:
            _state._file_digest = real_file_digest

    def test_wal_state_progression_normal_cycle(self):
        """Normal execution cleanly progresses: PREPARED -> APPLIED -> COMMITTED -> RESOLVED."""
        edit = self._create_pending_edit("module.py", "initial_code", "refactored_code")

        # Mock durability confirmed to simulate full fsync success
        real_fsync_parent = _state._fsync_parent
        _state._fsync_parent = lambda parent: True

        try:
            res = accept_edit(edit.edit_id)

            self.assertEqual(res.outcome, TransactionOutcome.ACCEPTED)
            self.assertEqual(len(res.succeeded_ids), 1)

            # Verify on-disk file content
            with open(edit.resolved_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "refactored_code")

            # Verify journal entries
            records = []
            with open(self.journal_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))

            event_types = [r["event_type"] for r in records]
            self.assertIn("PREPARED", event_types)
            self.assertIn("APPLIED", event_types)
            self.assertIn("COMMITTED", event_types)
            self.assertIn("RESOLVED", event_types)

            # Verify recovery report on clean restart
            report = load_and_reconcile_journal()
            self.assertFalse(report.requires_review)
            self.assertFalse(report.corruption_detected)
        finally:
            _state._fsync_parent = real_fsync_parent

    def test_journal_failed_after_applied_requires_reconciliation(self):
        """If APPLIED journal write fails after side effect occurred, returns RECONCILIATION_REQUIRED."""
        edit = self._create_pending_edit("state.py", "old_state", "new_state")

        # Mock journal write failure during APPLIED
        real_write_record = _state._write_journal_record

        def failing_write_record(rec: WalRecord) -> bool:
            if rec.event_type == "APPLIED":
                raise OSError("Disk quota exceeded on journal")
            return real_write_record(rec)

        _state._write_journal_record = failing_write_record
        try:
            res = accept_edit(edit.edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        finally:
            _state._write_journal_record = real_write_record


if __name__ == "__main__":
    unittest.main()
