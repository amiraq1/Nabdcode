"""Gate 10: No Blind Replay Verification."""

import dataclasses
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.accept_edits_state import (
    load_and_reconcile_journal,
    RecoveryReport,
    set_workspace_identity,
    set_journal_path,
    _close_journal,
    reset_session,
    _write_journal_record,
    _make_wal_record as _make_wal_record_orig,
    WalRecord,
)

def _make_wal_record(**kwargs) -> WalRecord:
    rec = _make_wal_record_orig(
        event_type=kwargs.get("event_type", "PREPARED"),
        operation_id=kwargs.get("operation_id", "op-1"),
        sequence=kwargs.get("sequence", 1),
        edit_id=kwargs.get("edit_id", "e-1"),
        operation_type=kwargs.get("operation_type", "ACCEPT"),
        target_path_relative=kwargs.get("target_path_relative", "f.txt")
    )
    if "schema_version" in kwargs:
        rec = dataclasses.replace(rec, schema_version=kwargs["schema_version"])
    return rec

def _teardown_journal():
    _close_journal()
    reset_session()


class TestGate10NoBlindReplay(unittest.TestCase):
    """Gate 10 tests ensuring loader never applies side-effects."""

    def setUp(self):
        _teardown_journal()

    def tearDown(self):
        _teardown_journal()

    def _verify_no_blind_replay(self, records: list[dict], expected_review: bool):
        td = Path(tempfile.mkdtemp())
        jpath = str(td / ".nabd" / "journal" / "journal.jsonl")
        jdir = Path(jpath).parent
        jdir.mkdir(parents=True, exist_ok=True)
        set_workspace_identity(str(td))
        set_journal_path(jpath)

        for rec in records:
            if rec == "CORRUPT":
                with open(jpath, "a") as f:
                    f.write("not json\n")
            else:
                _write_journal_record(rec)

        # Spies
        patch_accept = mock.patch("core.accept_edits_state.accept_edit")
        patch_reject = mock.patch("core.accept_edits_state.reject_edit")
        patch_apply = mock.patch("core.accept_edits_state._atomic_write")
        patch_rollback = mock.patch("core.accept_edits_state._rollback_snapshot")
        patch_replace = mock.patch("os.replace")
        patch_unlink = mock.patch("os.unlink")
        patch_remove = mock.patch("os.remove")
        patch_shutil = mock.patch("shutil.rmtree") # for cleanup
        
        with patch_accept as m_accept, patch_reject as m_reject, \
             patch_apply as m_apply, patch_rollback as m_rollback, \
             patch_replace as m_replace, patch_unlink as m_unlink, \
             patch_remove as m_remove, patch_shutil as m_shutil:
             
            report = load_and_reconcile_journal()
            
            # 1. Must return a RecoveryReport
            self.assertIsInstance(report, RecoveryReport)
            
            # 2. Spies must verify 0 calls
            self.assertEqual(m_accept.call_count, 0, "accept_edit called")
            self.assertEqual(m_reject.call_count, 0, "reject_edit called")
            self.assertEqual(m_apply.call_count, 0, "apply (_atomic_write) called")
            self.assertEqual(m_rollback.call_count, 0, "rollback called")
            self.assertEqual(m_replace.call_count, 0, "os.replace called")
            
            # Target unlink / snapshot deletion
            # Filter unlinks that might be innocuous (though loader shouldn't unlink anything)
            self.assertEqual(m_unlink.call_count, 0, f"os.unlink called: {m_unlink.mock_calls}")
            self.assertEqual(m_remove.call_count, 0, f"os.remove called: {m_remove.mock_calls}")
            self.assertEqual(m_shutil.call_count, 0, "cleanup called")
            
            # 3. Requires review flag
            self.assertEqual(report.requires_review, expected_review)
            
            return report

    def test_prepared_no_replay(self):
        records = [
            _make_wal_record(event_type="PREPARED")
        ]
        self._verify_no_blind_replay(records, True)

    def test_applied_no_replay(self):
        records = [
            _make_wal_record(event_type="PREPARED", sequence=1),
            _make_wal_record(event_type="APPLIED", sequence=2)
        ]
        self._verify_no_blind_replay(records, True)

    def test_committed_not_resolved_no_replay(self):
        records = [
            _make_wal_record(event_type="PREPARED", sequence=1),
            _make_wal_record(event_type="APPLIED", sequence=2),
            _make_wal_record(event_type="COMMITTED", sequence=3)
            # Missing RESOLVED
        ]
        self._verify_no_blind_replay(records, True)

    def test_reconciliation_required_no_replay(self):
        records = [
            _make_wal_record(event_type="PREPARED", sequence=1),
            # Missing APPLIED
            _make_wal_record(event_type="COMMITTED", sequence=3)
        ]
        self._verify_no_blind_replay(records, True)
        
    def test_corrupt_record_no_replay(self):
        records = ["CORRUPT"]
        report = self._verify_no_blind_replay(records, False)
        self.assertTrue(report.corruption_detected, f"Diagnostics: {report.diagnostics}")

    def test_unsupported_schema_no_replay(self):
        records = [
            _make_wal_record(schema_version=999)
        ]
        report = self._verify_no_blind_replay(records, False)
        self.assertTrue(report.unsupported_schema_detected)
