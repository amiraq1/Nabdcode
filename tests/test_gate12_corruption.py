"""Gate 12: Journal Corruption & Truncated-Tail Safety."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.accept_edits_state import (
    load_and_reconcile_journal,
    set_journal_path,
    set_workspace_identity,
    reset_session,
    _write_journal_record,
    _serialize_wal_record,
    JOURNAL_MAX_RECORD_BYTES,
)
from tests.test_gate10_no_blind_replay import _make_wal_record

class TestGate12Corruption(unittest.TestCase):

    def setUp(self):
        reset_session()
        self.td = tempfile.TemporaryDirectory()
        self.tmp_path = self.td.name
        self.jpath = os.path.join(self.tmp_path, "journal.jsonl")
        set_workspace_identity(self.tmp_path)
        set_journal_path(self.jpath)

    def tearDown(self):
        reset_session()
        self.td.cleanup()

    def _append_raw(self, data: bytes):
        with open(self.jpath, "ab") as f:
            f.write(data)

    def _verify_safety(self, expected_diagnostic_substrings, expected_requires_review=True, expected_valid_records=1):
        journal_size_before = os.path.getsize(self.jpath)
        
        with mock.patch("core.accept_edits_state.accept_edit") as m_accept, \
             mock.patch("core.accept_edits_state.reject_edit") as m_reject, \
             mock.patch("core.accept_edits_state._atomic_write") as m_apply, \
             mock.patch("core.accept_edits_state._rollback_snapshot") as m_rollback, \
             mock.patch("os.replace") as m_replace, \
             mock.patch("os.unlink") as m_unlink, \
             mock.patch("os.remove") as m_remove:
             
            report = load_and_reconcile_journal()
            
            # verify zero side effects
            self.assertEqual(m_accept.call_count, 0)
            self.assertEqual(m_reject.call_count, 0)
            self.assertEqual(m_apply.call_count, 0)
            self.assertEqual(m_rollback.call_count, 0)
            self.assertEqual(m_replace.call_count, 0)
            self.assertEqual(m_unlink.call_count, 0)
            self.assertEqual(m_remove.call_count, 0)
            
            # verify journal not mutated
            self.assertEqual(os.path.getsize(self.jpath), journal_size_before)
            
            # verify review requirement
            self.assertEqual(report.requires_review, expected_requires_review)
            
            # verify prior valid records preserved
            self.assertEqual(len(report.operations), expected_valid_records)
            
            # verify diagnostics
            diagnostics_str = " ".join(report.diagnostics)
            for sub in expected_diagnostic_substrings:
                self.assertIn(sub, diagnostics_str)
                
            return report

    def test_truncated_tail_detected_not_replayed(self):
        _write_journal_record(_make_wal_record(sequence=1))
        self._append_raw(b'{"record_id":"trunca')
        report = self._verify_safety(["TRUNCATED_TAIL"], expected_valid_records=1)
        self.assertTrue(report.truncated_tail_detected)

    def test_corrupt_middle_record_detected(self):
        _write_journal_record(_make_wal_record(sequence=1))
        self._append_raw(b'{"record_id": "bad", \n')
        _write_journal_record(_make_wal_record(sequence=2, event_type="APPLIED"))
        report = self._verify_safety(["JSON_DECODE_ERROR"], expected_valid_records=2)
        self.assertTrue(report.corruption_detected)

    def test_checksum_mismatch_detected(self):
        _write_journal_record(_make_wal_record(sequence=1))
        rec = _make_wal_record(sequence=2, event_type="APPLIED")
        raw = _serialize_wal_record(rec)
        modified = raw.replace(b'"APPLIED"', b'"REJECT "')
        self._append_raw(modified)
        report = self._verify_safety(["CORRUPT_RECORD"], expected_valid_records=1)
        self.assertTrue(report.corruption_detected)

    def test_invalid_utf8_detected(self):
        _write_journal_record(_make_wal_record(sequence=1))
        self._append_raw(b'{"record_id": "\xff\xff"}\n')
        report = self._verify_safety(["JOURNAL_ENCODING_ERROR"], expected_valid_records=1)
        self.assertTrue(report.corruption_detected)

    def test_oversized_record_rejected_safely(self):
        _write_journal_record(_make_wal_record(sequence=1))
        oversized = b'{"a":"' + b'x' * (JOURNAL_MAX_RECORD_BYTES + 10) + b'"}\n'
        self._append_raw(oversized)
        report = self._verify_safety(["OVERSIZED_RECORD"], expected_valid_records=1)
        self.assertTrue(report.corruption_detected)

    def test_valid_final_record_without_newline_is_handled(self):
        rec = _make_wal_record(sequence=1)
        raw = _serialize_wal_record(rec)
        # Remove trailing newline
        raw = raw.rstrip(b'\n')
        self._append_raw(raw)
        
        # Valid JSON, valid checksum -> no TRUNCATED_TAIL, no CORRUPT_RECORD.
        report = self._verify_safety([], expected_valid_records=1)
        self.assertFalse(report.truncated_tail_detected)
        self.assertFalse(report.corruption_detected)

    def test_valid_prior_records_preserved(self):
        _write_journal_record(_make_wal_record(sequence=1))
        _write_journal_record(_make_wal_record(sequence=2, event_type="APPLIED"))
        self._append_raw(b"CORRUPT\n")
        self._verify_safety(["JSON_DECODE_ERROR"], expected_valid_records=2)

    def test_corruption_does_not_mutate_journal(self):
        _write_journal_record(_make_wal_record(sequence=1))
        self._append_raw(b"CORRUPT\n")
        self._verify_safety(["JSON_DECODE_ERROR"], expected_valid_records=1)

    def test_corruption_performs_zero_side_effects(self):
        _write_journal_record(_make_wal_record(sequence=1))
        self._append_raw(b"CORRUPT\n")
        self._verify_safety(["JSON_DECODE_ERROR"], expected_valid_records=1)

    def test_diagnostics_do_not_leak_raw_content(self):
        _write_journal_record(_make_wal_record(sequence=1))
        secret = "SUPER_SECRET_KEY_123"
        self._append_raw(f'INVALID JSON WITH {secret}\n'.encode())
        
        report = self._verify_safety(["JSON_DECODE_ERROR"], expected_valid_records=1)
        diag = " ".join(report.diagnostics)
        self.assertNotIn(secret, diag)
        self.assertIn("JSON_DECODE_ERROR", diag)

if __name__ == "__main__":
    unittest.main()
