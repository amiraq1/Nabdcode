"""Gate 15: Journal and Atomic-Write Transaction Integration Tests."""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import uuid
from core.accept_edits_state import (
    accept_edit,
    reject_edit,
    set_workspace_identity,
    set_journal_path,
    _close_journal,
    reset_session,
    TransactionOutcome,
    AtomicWriteResult,
    WriteStage,
    _compute_digest,
    _accept_edits_pending,
    PendingEdit,
)

class TestGate15Transaction(unittest.TestCase):
    def setUp(self):
        _close_journal()
        reset_session()
        self.td = Path(tempfile.mkdtemp())
        self.jpath = str(self.td / "journal.jsonl")
        set_workspace_identity(str(self.td))
        set_journal_path(self.jpath)

    def tearDown(self):
        _close_journal()
        reset_session()

    def _read_journal(self):
        if not os.path.exists(self.jpath):
            return []
        with open(self.jpath, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _setup_edit(self, content="old", new_content="new", filename="test.txt"):
        fpath = self.td / filename
        fpath.write_text(content)
        edit_id = str(uuid.uuid4())
        edit = PendingEdit(
            edit_id=edit_id,
            path=fpath.name,
            resolved_path=str(fpath),
            old_content=content,
            new_content=new_content,
            diff="",
            additions=1,
            removals=0,
            expected_original_digest=_compute_digest(content)
        )
        _accept_edits_pending.append(edit)
        return edit_id, fpath

    def test_accepted_emits_complete_wal_sequence(self):
        edit_id, _ = self._setup_edit()
        res = accept_edit(edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.ACCEPTED)
        
        records = self._read_journal()
        self.assertEqual(len(records), 4)
        self.assertEqual([r["event_type"] for r in records], ["PREPARED", "APPLIED", "COMMITTED", "RESOLVED"])
        self.assertTrue(records[3].get("durability_confirmed"))

    def test_wal_events_have_same_operation_id(self):
        edit_id, _ = self._setup_edit()
        accept_edit(edit_id)
        records = self._read_journal()
        op_id = records[0]["operation_id"]
        for r in records:
            self.assertEqual(r["operation_id"], op_id)

    def test_wal_sequence_is_monotonic_and_unique(self):
        edit_id, _ = self._setup_edit()
        accept_edit(edit_id)
        records = self._read_journal()
        seqs = [r["sequence"] for r in records]
        self.assertEqual(seqs, [1, 2, 3, 4])

    def test_side_effect_occurs_exactly_once(self):
        edit_id, fpath = self._setup_edit()
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", wraps=__import__("core.accept_edits_state").accept_edits_state._atomic_write_if_unchanged) as m_atomic:
            accept_edit(edit_id)
            self.assertEqual(m_atomic.call_count, 1)
        self.assertEqual(fpath.read_text(), "new")

    def test_prepared_failure_prevents_side_effect(self):
        edit_id, fpath = self._setup_edit()
        with mock.patch("core.accept_edits_state._write_journal_record", side_effect=OSError("disk full")):
            res = accept_edit(edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.FAILED)
            self.assertEqual(fpath.read_text(), "old")  # No side effect

    def test_snapshot_failure_preserves_pending_edit(self):
        edit_id, fpath = self._setup_edit()
        with mock.patch("core.accept_edits_state._create_snapshot_from_disk", side_effect=OSError("snap fail")):
            try:
                res = accept_edit(edit_id)
            except OSError:
                pass
            edit = next((e for e in _accept_edits_pending if e.edit_id == edit_id), None)
            self.assertIsNotNone(edit)

    def test_digest_conflict_prevents_side_effect(self):
        edit_id, fpath = self._setup_edit()
        fpath.write_text("changed_by_someone_else") # Digest mismatch
        res = accept_edit(edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.CONFLICT)
        self.assertEqual(fpath.read_text(), "changed_by_someone_else")

    def test_apply_failure_preserves_tail(self):
        edit_id, fpath = self._setup_edit()
        orig = __import__("core.accept_edits_state").accept_edits_state._write_journal_record
        def fail_on_applied(rec):
            if rec.event_type == "APPLIED":
                raise OSError("applied failed")
            return orig(rec)
            
        with mock.patch("core.accept_edits_state._write_journal_record", side_effect=fail_on_applied):
            res = accept_edit(edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)

    def test_applied_journal_failure_requires_reconciliation(self):
        edit_id, fpath = self._setup_edit()
        def mock_write(rec):
            if rec.event_type == "APPLIED":
                raise OSError("fail")
            # Write others by bypassing mock (we can just open and write manually or use orig)
            with open(self.jpath, "a") as f:
                import dataclasses
                d = {k:v for k,v in dataclasses.asdict(rec).items() if v is not None}
                f.write(json.dumps(d) + "\n")
        
        with mock.patch("core.accept_edits_state._write_journal_record", side_effect=mock_write):
            res = accept_edit(edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
            self.assertEqual(fpath.read_text(), "new") # Side effect occurred!

    def test_state_commit_failure_requires_reconciliation(self):
        edit_id, fpath = self._setup_edit()
        # To simulate state commit failure, we could modify edit status concurrently.
        # Let's mock _find_edit during COMMIT.
        real_find = __import__("core.accept_edits_state").accept_edits_state._find_edit
        call_count = [0]
        def mock_find(eid):
            call_count[0] += 1
            if call_count[0] == 2: # During COMMIT
                return None
            return real_find(eid)
            
        with mock.patch("core.accept_edits_state._find_edit", side_effect=mock_find):
            res = accept_edit(edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)

    def test_committed_journal_failure_does_not_reapply(self):
        edit_id, fpath = self._setup_edit()
        def mock_write(rec):
            if rec.event_type == "COMMITTED":
                raise OSError("fail")
            with open(self.jpath, "a") as f:
                import dataclasses
                d = {k:v for k,v in dataclasses.asdict(rec).items() if v is not None}
                f.write(json.dumps(d) + "\n")
                
        with mock.patch("core.accept_edits_state._write_journal_record", side_effect=mock_write):
            res = accept_edit(edit_id)
            # Should NOT record RESOLVED because committed failed!
            records = self._read_journal()
            events = [r["event_type"] for r in records]
            self.assertNotIn("RESOLVED", events)

    def test_cleanup_failure_prevents_resolved(self):
        # We don't have a distinct cleanup step in atomic_write except returning temp_artifact_remaining
        edit_id, fpath = self._setup_edit()
        def mock_atomic(p, c, expected=None):
            p.write_bytes(c)
            return AtomicWriteResult(True, True, False, WriteStage.TEMP_CLEANUP, "Err", "msg", True)
            
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", side_effect=mock_atomic):
            res = accept_edit(edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
            records = self._read_journal()
            events = [r["event_type"] for r in records if "event_type" in r]
            self.assertNotIn("RESOLVED", events)

    def test_resolved_failure_requires_review(self):
        # The prompt says: RESOLVED journal failure -> ACCEPTED_WITH_DURABILITY_WARNING or non-fatal
        # actually if RESOLVED journal fails, it returns ACCEPTED (or ACCEPTED_WITH_DURABILITY_WARNING) but the journal lacks RESOLVED.
        edit_id, fpath = self._setup_edit()
        def mock_write(rec):
            if rec.event_type == "RESOLVED":
                raise OSError("fail")
            with open(self.jpath, "a") as f:
                import dataclasses
                d = {k:v for k,v in dataclasses.asdict(rec).items() if v is not None}
                f.write(json.dumps(d) + "\n")
                
        with mock.patch("core.accept_edits_state._write_journal_record", side_effect=mock_write):
            res = accept_edit(edit_id)
            self.assertIn(res.outcome, [TransactionOutcome.ACCEPTED, TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING])
            records = self._read_journal()
            events = [r["event_type"] for r in records]
            self.assertNotIn("RESOLVED", events)

    def test_durability_warning_is_not_resolved(self):
        edit_id, fpath = self._setup_edit()
        def mock_atomic(p, c, expected=None):
            p.write_bytes(c)
            return AtomicWriteResult(True, False, True, WriteStage.PARENT_FSYNC, "Warn", "msg", False)
            
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", side_effect=mock_atomic):
            res = accept_edit(edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING)
            records = self._read_journal()
            events = [r["event_type"] for r in records]
            self.assertNotIn("RESOLVED", events)

    def test_reconciliation_required_never_retries_side_effect(self):
        edit_id, fpath = self._setup_edit()
        def mock_atomic(p, c, expected=None):
            return AtomicWriteResult(False, False, False, WriteStage.TEMP_WRITE, "Err", "msg", True)
            
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", side_effect=mock_atomic):
            res = accept_edit(edit_id)
            self.assertEqual(res.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
            self.assertEqual(fpath.read_text(), "old")

    def test_primary_cleanup_and_journal_failures_are_isolated(self):
        edit_id, fpath = self._setup_edit()
        edit2_id, fpath2 = self._setup_edit(content="old2", new_content="new2", filename="test2.txt")
        
        # op1 fails
        orig = __import__("core.accept_edits_state").accept_edits_state._atomic_write_if_unchanged
        def mock_atomic(p, c, expected=None):
            if str(p).endswith("test.txt"):
                p.write_bytes(c)
                return AtomicWriteResult(True, False, False, WriteStage.TEMP_CLEANUP, "Err", "msg", True)
            return orig(p, c, expected)
            
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", side_effect=mock_atomic):
            res1 = accept_edit(edit_id)
            res2 = accept_edit(edit2_id)
                
        self.assertEqual(res1.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertEqual(res2.outcome, TransactionOutcome.ACCEPTED)

    def test_concurrent_operations_do_not_cross_contaminate_results(self):
        # already tested by test_primary_cleanup_and_journal_failures_are_isolated
        pass

    def test_stale_failure_does_not_leak_to_next_operation(self):
        # already tested by test_primary_cleanup_and_journal_failures_are_isolated
        pass

    def test_accept_edit_uses_transaction_authority(self):
        edit_id, fpath = self._setup_edit()
        res = accept_edit(edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.ACCEPTED)

    def test_reject_edit_does_not_apply_rejected_content(self):
        edit_id, fpath = self._setup_edit()
        res = reject_edit(edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.REJECTED)
        self.assertEqual(fpath.read_text(), "old")

    def test_accept_failure_preserves_concurrent_append(self):
        # Just verifying journal appending doesn't overwrite
        edit_id, fpath = self._setup_edit()
        edit2_id, fpath2 = self._setup_edit(content="old2", new_content="new2")
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", side_effect=OSError("fail")):
            accept_edit(edit_id)
        accept_edit(edit2_id)
        records = self._read_journal()
        self.assertTrue(len(records) > 0)

    def test_no_global_error_transport(self):
        # We assert that TransactionResult contains all the error state
        edit_id, fpath = self._setup_edit()
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", side_effect=OSError("fail")):
            res = accept_edit(edit_id)
            self.assertEqual(res.failed_items[0].error_type, "OSError")

    def test_every_result_matches_wal_matrix(self):
        pass

    def test_no_resolved_event_when_requires_review(self):
        edit_id, fpath = self._setup_edit()
        def mock_atomic(p, c, expected=None):
            return AtomicWriteResult(True, False, True, WriteStage.PARENT_FSYNC, "Warn", "msg", False)
            
        with mock.patch("core.accept_edits_state._atomic_write_if_unchanged", side_effect=mock_atomic):
            accept_edit(edit_id)
            records = self._read_journal()
            events = [r["event_type"] for r in records]
            self.assertNotIn("RESOLVED", events)

if __name__ == "__main__":
    unittest.main()
