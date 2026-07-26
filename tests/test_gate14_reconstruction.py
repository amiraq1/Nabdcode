"""Gate 14: Pure Operation-State Reconstruction Tests."""

import dataclasses
import hashlib
import json
import unittest
from unittest import mock

from core.accept_edits_state import (
    reconstruct_operations,
    WalRecord,
    JOURNAL_SCHEMA_VERSION,
    _verify_record_checksum,
)
from tests.test_gate10_no_blind_replay import _make_wal_record

def _make_record(**kwargs):
    rec = _make_wal_record(**kwargs)
    updates = {}
    for k in ["durability_confirmed", "workspace_id", "record_id", "schema_version"]:
        if k in kwargs:
            updates[k] = kwargs[k]
    
    if updates:
        rec = dataclasses.replace(rec, **updates)
        
    d = dataclasses.asdict(rec)
    from core.accept_edits_state import _compute_record_checksum
    rec = dataclasses.replace(rec, checksum=_compute_record_checksum(d))
    return rec


class TestGate14Reconstruction(unittest.TestCase):

    def test_reconstruction_is_pure_and_performs_no_io(self):
        with mock.patch("os.open") as m_open, \
             mock.patch("os.read") as m_read, \
             mock.patch("os.write") as m_write, \
             mock.patch("os.replace") as m_replace, \
             mock.patch("os.unlink") as m_unlink, \
             mock.patch("core.accept_edits_state._write_all") as m_write_all:
             
            rec = _make_record(sequence=1, event_type="PREPARED")
            reconstruct_operations([rec])
            
            m_open.assert_not_called()
            m_read.assert_not_called()
            m_write.assert_not_called()
            m_replace.assert_not_called()
            m_unlink.assert_not_called()
            m_write_all.assert_not_called()

    def test_reconstructs_prepared_operation(self):
        rec = _make_record(sequence=1, event_type="PREPARED")
        report = reconstruct_operations([rec])
        self.assertTrue(report.requires_review)
        self.assertEqual(len(report.diagnostics), 0)

    def test_reconstructs_applied_not_committed(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec2 = _make_record(sequence=2, event_type="APPLIED")
        report = reconstruct_operations([rec1, rec2])
        self.assertTrue(report.requires_review)
        self.assertEqual(len(report.diagnostics), 0)

    def test_reconstructs_committed_not_resolved(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec2 = _make_record(sequence=2, event_type="APPLIED")
        rec3 = _make_record(sequence=3, event_type="COMMITTED")
        report = reconstruct_operations([rec1, rec2, rec3])
        self.assertTrue(report.requires_review)
        self.assertEqual(len(report.diagnostics), 0)

    def test_reconstructs_resolved_operation(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec2 = _make_record(sequence=2, event_type="APPLIED")
        rec3 = _make_record(sequence=3, event_type="COMMITTED")
        rec4 = _make_record(sequence=4, event_type="RESOLVED", durability_confirmed=True)
        report = reconstruct_operations([rec1, rec2, rec3, rec4])
        self.assertFalse(report.requires_review)
        self.assertEqual(len(report.diagnostics), 0)

    def test_reconciliation_required_needs_manual_review(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec2 = _make_record(sequence=2, event_type="RECONCILIATION_REQUIRED")
        report = reconstruct_operations([rec1, rec2])
        self.assertTrue(report.requires_review)
        self.assertEqual(len(report.diagnostics), 0)

    def test_applied_without_prepared_is_invalid(self):
        rec = _make_record(sequence=2, event_type="APPLIED")
        report = reconstruct_operations([rec])
        diag = " ".join(report.diagnostics)
        self.assertIn("INVALID_EVENT_SEQUENCE", diag)
        self.assertIn("APPLIED without PREPARED", diag)

    def test_committed_without_applied_is_invalid(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec2 = _make_record(sequence=3, event_type="COMMITTED")
        report = reconstruct_operations([rec1, rec2])
        diag = " ".join(report.diagnostics)
        self.assertIn("INVALID_EVENT_SEQUENCE", diag)

    def test_resolved_without_committed_is_invalid(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec2 = _make_record(sequence=2, event_type="APPLIED")
        rec3 = _make_record(sequence=4, event_type="RESOLVED")
        report = reconstruct_operations([rec1, rec2, rec3])
        diag = " ".join(report.diagnostics)
        self.assertIn("INVALID_EVENT_SEQUENCE", diag)

    def test_sequence_regression_is_invalid(self):
        rec1 = _make_record(sequence=2, event_type="APPLIED")
        rec2 = _make_record(sequence=1, event_type="PREPARED")
        # Same operation_id is default in _make_record
        report = reconstruct_operations([rec1, rec2])
        diag = " ".join(report.diagnostics)
        self.assertIn("INVALID_EVENT_SEQUENCE", diag)
        self.assertIn("seq regression", diag)

    def test_conflicting_duplicate_sequence_is_reported(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED", record_id="r1")
        rec2 = _make_record(sequence=1, event_type="APPLIED", record_id="r2") # Same sequence, different event!
        report = reconstruct_operations([rec1, rec2])
        diag = " ".join(report.diagnostics)
        self.assertIn("CONFLICTING_DUPLICATE_EVENT", diag)

    def test_duplicate_record_id_is_reported(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED", record_id="r1")
        rec2 = _make_record(sequence=2, event_type="APPLIED", record_id="r1")
        report = reconstruct_operations([rec1, rec2])
        diag = " ".join(report.diagnostics)
        self.assertIn("DUPLICATE_RECORD_ID", diag)

    def test_operation_identity_conflict_is_reported(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED", edit_id="edit1")
        rec2 = _make_record(sequence=2, event_type="APPLIED", edit_id="edit2")
        report = reconstruct_operations([rec1, rec2])
        diag = " ".join(report.diagnostics)
        self.assertIn("OPERATION_IDENTITY_CONFLICT", diag)

    def test_foreign_workspace_record_is_not_merged(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED", workspace_id="ws1")
        report = reconstruct_operations([rec1], current_workspace_id="ws2")
        diag = " ".join(report.diagnostics)
        self.assertIn("FOREIGN_WORKSPACE_RECORD", diag)
        self.assertTrue(report.foreign_workspace_records)

    def test_unsupported_event_type_is_preserved(self):
        rec1 = _make_record(sequence=1, event_type="FUTURE_EVENT_TYPE")
        report = reconstruct_operations([rec1])
        diag = " ".join(report.diagnostics)
        self.assertIn("UNSUPPORTED_EVENT_TYPE", diag)

    def test_unsupported_schema_is_preserved(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec1 = dataclasses.replace(rec1, schema_version=999)
        report = reconstruct_operations([rec1])
        diag = " ".join(report.diagnostics)
        self.assertIn("UNSUPPORTED_SCHEMA", diag)
        self.assertTrue(report.unsupported_schema_detected)

    def test_checksum_mismatch_is_corrupt(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        # Corrupt it manually
        rec1 = dataclasses.replace(rec1, checksum="bad_checksum")
        report = reconstruct_operations([rec1])
        diag = " ".join(report.diagnostics)
        self.assertIn("CORRUPT_RECORD", diag)
        self.assertTrue(report.corruption_detected)

    def test_conflicting_terminal_events_are_invalid(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec2 = _make_record(sequence=2, event_type="FAILED", record_id="r2")
        rec3 = _make_record(sequence=3, event_type="RESOLVED", record_id="r3")
        report = reconstruct_operations([rec1, rec2, rec3])
        diag = " ".join(report.diagnostics)
        self.assertIn("CONFLICTING_TERMINAL_EVENTS", diag)

    def test_input_order_does_not_change_result(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED", operation_id="op1", record_id="r1")
        rec2 = _make_record(sequence=1, event_type="PREPARED", operation_id="op2", record_id="r2")
        rec3 = _make_record(sequence=2, event_type="APPLIED", operation_id="op1", record_id="r3")
        
        rep1 = reconstruct_operations([rec1, rec2, rec3])
        rep2 = reconstruct_operations([rec2, rec1, rec3])
        
        self.assertEqual(rep1.requires_review, rep2.requires_review)
        self.assertEqual(set(rep1.diagnostics), set(rep2.diagnostics))

    def test_input_records_are_not_mutated(self):
        rec1 = _make_record(sequence=1, event_type="PREPARED")
        rec1_copy = dataclasses.replace(rec1)
        
        reconstruct_operations([rec1])
        self.assertEqual(rec1, rec1_copy)

    def test_reconstruction_never_replays_side_effects(self):
        with mock.patch("core.accept_edits_state._atomic_write") as m_apply:
            rec = _make_record(sequence=1, event_type="PREPARED")
            reconstruct_operations([rec])
            m_apply.assert_not_called()

    def test_diagnostics_do_not_leak_raw_content(self):
        rec = _make_record(sequence=1, event_type="PREPARED", target_path_relative="MY_SECRET_PASSWORD")
        # Make it invalid by duplicating it (will cause OPERATION_IDENTITY_CONFLICT? No, same edit_id. Duplicate sequence!)
        rec2 = _make_record(sequence=1, event_type="APPLIED", record_id="r2", target_path_relative="MY_SECRET_PASSWORD")
        report = reconstruct_operations([rec, rec2])
        diag = " ".join(report.diagnostics)
        self.assertNotIn("MY_SECRET_PASSWORD", diag)

if __name__ == "__main__":
    unittest.main()
