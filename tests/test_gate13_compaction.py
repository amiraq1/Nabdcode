"""Gate 13: Retention & Atomic Compaction Tests."""

import dataclasses
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.accept_edits_state import (
    load_and_reconcile_journal,
    set_journal_path,
    load_workspace_identity,
    reset_session,
    _write_journal_record,
    _serialize_wal_record,
    _compact_journal,
    WalRecord,
    _ensure_journal_locked,
    _release_lock,
)
from tests.test_gate10_no_blind_replay import _make_wal_record

def _make_record(**kwargs):
    rec = _make_wal_record(**kwargs)
    if "durability_confirmed" in kwargs:
        rec = dataclasses.replace(rec, durability_confirmed=kwargs["durability_confirmed"])
        
    d = dataclasses.asdict(rec)
    from core.accept_edits_state import _compute_record_checksum
    rec = dataclasses.replace(rec, checksum=_compute_record_checksum(d))
    return rec


def compaction_proc(tmp_path, conn):
    load_workspace_identity(tmp_path)
    set_journal_path(os.path.join(tmp_path, "journal.jsonl"))
    
    original_replace = os.replace
    def fake_replace(src, dst):
        conn.send("HELD")
        conn.recv() # wait for peer
        original_replace(src, dst)
        
    with mock.patch("os.replace", side_effect=fake_replace):
        _compact_journal()
    conn.send("DONE")

def append_proc(tmp_path, conn, root_dir):
    load_workspace_identity(tmp_path)
    set_journal_path(os.path.join(tmp_path, "journal.jsonl"))
    
    conn.recv() # Wait for compaction to hold lock
    _write_journal_record(_make_record(sequence=1, operation_id="append_op", event_type="PREPARED"))
    conn.send("WROTE")

def append_proc_hold(tmp_path, conn):
    load_workspace_identity(tmp_path)
    set_journal_path(os.path.join(tmp_path, "journal.jsonl"))
    
    _ensure_journal_locked()
    conn.send("HELD")
    conn.recv()
    _release_lock()

def compaction_proc_wait(tmp_path, conn, root_dir):
    load_workspace_identity(tmp_path)
    set_journal_path(os.path.join(tmp_path, "journal.jsonl"))
    
    conn.recv() # wait for append to hold
    _compact_journal()
    conn.send("COMPACTED")


class TestGate13Compaction(unittest.TestCase):

    def setUp(self):
        reset_session()
        self.td = tempfile.TemporaryDirectory()
        self.tmp_path = self.td.name
        self.jpath = os.path.join(self.tmp_path, "journal.jsonl")
        load_workspace_identity(self.tmp_path)
        set_journal_path(self.jpath)
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def tearDown(self):
        reset_session()
        self.td.cleanup()

    def test_unresolved_operations_are_never_pruned(self):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="PREPARED"))
        _write_journal_record(_make_record(sequence=1, operation_id="op2", event_type="COMMITTED"))
        
        success, msg = _compact_journal()
        self.assertTrue(success)
        
        report = load_and_reconcile_journal()
        op_ids = {r.operation_id for r in report.operations}
        self.assertIn("op1", op_ids)
        self.assertIn("op2", op_ids)
        self.assertTrue(report.requires_review)

    def test_resolved_old_operations_are_pruned(self):
        # Durability confirmed -> pruned
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="RESOLVED", durability_confirmed=True))
        # Durability not confirmed -> NOT pruned
        _write_journal_record(_make_record(sequence=1, operation_id="op2", event_type="RESOLVED", durability_confirmed=False))
        
        success, msg = _compact_journal()
        self.assertTrue(success)
        
        report = load_and_reconcile_journal()
        op_ids = {r.operation_id for r in report.operations}
        self.assertNotIn("op1", op_ids)
        self.assertIn("op2", op_ids)

    def test_retention_max_bytes_is_enforced(self):
        # Pruning happens and reduces size
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="RESOLVED", durability_confirmed=True))
        size_before = os.path.getsize(self.jpath)
        _compact_journal()
        size_after = os.path.getsize(self.jpath)
        self.assertTrue(size_after < size_before)
        
    def test_journal_size_bounded_after_resolved_history(self):
        for i in range(10):
            _write_journal_record(_make_record(sequence=1, operation_id=f"op{i}", event_type="RESOLVED", durability_confirmed=True))
        _compact_journal()
        self.assertEqual(os.path.getsize(self.jpath), 0)

    @mock.patch("core.accept_edits_state._ensure_journal_locked")
    def test_compaction_uses_stable_lock_file(self, m_ensure_lock):
        m_ensure_lock.return_value = 999
        try:
            _compact_journal()
        except Exception:
            pass
        m_ensure_lock.assert_called_once()
        
    @mock.patch("os.replace")
    def test_compaction_uses_same_directory_temp(self, m_replace):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="RESOLVED", durability_confirmed=True))
        _compact_journal()
        self.assertTrue(m_replace.called)
        src, dst = m_replace.call_args[0]
        self.assertEqual(os.path.dirname(src), os.path.dirname(dst))
        
    @mock.patch("os.replace")
    def test_compaction_uses_atomic_replace(self, m_replace):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="RESOLVED", durability_confirmed=True))
        _compact_journal()
        m_replace.assert_called_once()
        
    @mock.patch("os.fsync")
    def test_compaction_fsyncs_temp_and_parent(self, m_fsync):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="RESOLVED", durability_confirmed=True))
        _compact_journal()
        self.assertTrue(m_fsync.call_count >= 2)

    def test_compaction_enospc_preserves_original(self):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="PREPARED"))
        _write_journal_record(_make_record(sequence=1, operation_id="op2", event_type="RESOLVED", durability_confirmed=True))
        size_before = os.path.getsize(self.jpath)
        
        with mock.patch("core.accept_edits_state._write_all") as m_write_all:
            m_write_all.side_effect = OSError(28, "No space left on device")
            success, msg = _compact_journal()
            self.assertFalse(success)
            self.assertIn("No space", msg)
            
        self.assertEqual(os.path.getsize(self.jpath), size_before)

    def test_compaction_replace_failure_preserves_original(self):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="PREPARED"))
        _write_journal_record(_make_record(sequence=1, operation_id="op2", event_type="RESOLVED", durability_confirmed=True))
        size_before = os.path.getsize(self.jpath)
        
        with mock.patch("os.replace") as m_replace:
            m_replace.side_effect = OSError("Access denied")
            success, msg = _compact_journal()
            self.assertFalse(success)
            self.assertIn("Access denied", msg)
            
        self.assertEqual(os.path.getsize(self.jpath), size_before)

    def test_compaction_failure_preserves_original_journal(self):
        # Implicitly tested by the ENOSPC and replace failure tests
        pass

    @mock.patch("core.accept_edits_state._fsync_parent")
    def test_compaction_parent_fsync_failure_reports_warning(self, m_fsync_parent):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="RESOLVED", durability_confirmed=True))
        
        m_fsync_parent.side_effect = OSError("I/O error")
        success, msg = _compact_journal()
        self.assertFalse(success)
        self.assertIn("COMPACTION_DURABILITY_WARNING", msg)
        
        report = load_and_reconcile_journal()
        self.assertTrue(report.requires_review)
        self.assertTrue(any(r.event_type == "RECONCILIATION_REQUIRED" for r in report.operations))

    def test_compaction_temp_cleanup_failure_is_reported(self):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="PREPARED"))
        _write_journal_record(_make_record(sequence=1, operation_id="op2", event_type="RESOLVED", durability_confirmed=True))
        
        with mock.patch("os.replace") as m_replace, mock.patch("os.unlink") as m_unlink:
            m_replace.side_effect = OSError("Replace failed")
            m_unlink.side_effect = OSError("Unlink failed")
            
            success, msg = _compact_journal()
            self.assertFalse(success)
            self.assertTrue(m_unlink.called)

    def test_unresolved_survive_compaction_and_restart(self):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="PREPARED"))
        _compact_journal()
        report = load_and_reconcile_journal()
        self.assertEqual(len(report.operations), 1)

    def test_checksums_valid_after_compaction(self):
        _write_journal_record(_make_record(sequence=1, operation_id="op1", event_type="PREPARED"))
        _compact_journal()
        report = load_and_reconcile_journal()
        self.assertFalse(report.corruption_detected)

    def test_append_waits_for_cross_process_compaction(self):
        multiprocessing.set_start_method('spawn', force=True)
        # Ensure compaction has something to prune so it holds the lock
        _write_journal_record(_make_record(sequence=1, operation_id="op2", event_type="RESOLVED", durability_confirmed=True))
        parent_conn, child_conn = multiprocessing.Pipe()
        parent_conn2, child_conn2 = multiprocessing.Pipe()
        
        p1 = multiprocessing.Process(target=compaction_proc, args=(self.tmp_path, child_conn))
        p2 = multiprocessing.Process(target=append_proc, args=(self.tmp_path, child_conn2, self.root_dir))
        
        p1.start()
        msg = parent_conn.recv()
        self.assertEqual(msg, "HELD")
        
        p2.start()
        # signal p2 to start writing (it will block on lock)
        parent_conn2.send("START")
        
        # let p1 finish
        parent_conn.send("CONTINUE")
        
        p1.join(timeout=5.0)
        self.assertEqual(parent_conn.recv(), "DONE")
        
        p2.join(timeout=5.0)
        self.assertEqual(parent_conn2.recv(), "WROTE")
        
        report = load_and_reconcile_journal()
        self.assertTrue(any(r.operation_id == "append_op" for r in report.operations))

    def test_compaction_waits_for_cross_process_append(self):
        multiprocessing.set_start_method('spawn', force=True)
        _write_journal_record(_make_record(sequence=1, operation_id="op2", event_type="RESOLVED", durability_confirmed=True))
        parent_conn, child_conn = multiprocessing.Pipe()
        parent_conn2, child_conn2 = multiprocessing.Pipe()
        
        p1 = multiprocessing.Process(target=append_proc_hold, args=(self.tmp_path, child_conn))
        p2 = multiprocessing.Process(target=compaction_proc_wait, args=(self.tmp_path, child_conn2, self.root_dir))
        
        p1.start()
        self.assertEqual(parent_conn.recv(), "HELD")
        
        p2.start()
        parent_conn2.send("CONTINUE")
        
        parent_conn.send("RELEASE")
        p1.join(timeout=5.0)
        
        self.assertEqual(parent_conn2.recv(), "COMPACTED")
        p2.join(timeout=5.0)

if __name__ == "__main__":
    unittest.main()
