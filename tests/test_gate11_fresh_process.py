"""Gate 11: Fresh-Process Restart Verification."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

PROCESS_A_SCRIPT = """
import os
import sys
import uuid
import time

# Ensure we can import core
sys.path.insert(0, sys.argv[4])

from core.accept_edits_state import _write_journal_record, WalRecord, set_journal_path, set_workspace_identity

def main():
    stage = sys.argv[1]
    pipe_fd = int(sys.argv[2])
    tmp_path = sys.argv[3]
    
    set_workspace_identity(tmp_path)
    jpath = os.path.join(tmp_path, "journal.jsonl")
    set_journal_path(jpath)
    
    op_id = "op-gate11"
    
    # We must write and fsync. _write_journal_record does both.
    if stage in ["PREPARED", "APPLIED", "COMMITTED"]:
        _write_journal_record(WalRecord(
            record_id=str(uuid.uuid4()),
            workspace_id="", workspace_root_fingerprint="",
            operation_id=op_id, sequence=1, event_type="PREPARED",
            edit_id="e1", operation_type="ACCEPT", target_path_relative="f.txt",
            expected_original_digest="abc", intended_result_digest="def"
        ))
    if stage in ["APPLIED", "COMMITTED"]:
        _write_journal_record(WalRecord(
            record_id=str(uuid.uuid4()),
            workspace_id="", workspace_root_fingerprint="",
            operation_id=op_id, sequence=2, event_type="APPLIED",
            edit_id="e1", operation_type="ACCEPT", target_path_relative="f.txt",
            expected_original_digest="abc", intended_result_digest="def"
        ))
    if stage in ["COMMITTED"]:
        _write_journal_record(WalRecord(
            record_id=str(uuid.uuid4()),
            workspace_id="", workspace_root_fingerprint="",
            operation_id=op_id, sequence=3, event_type="COMMITTED",
            edit_id="e1", operation_type="ACCEPT", target_path_relative="f.txt",
            expected_original_digest="abc", intended_result_digest="def"
        ))
        
    with os.fdopen(pipe_fd, "w") as f:
        f.write(f"REACHED:{stage}\\n")
        f.flush()
        
    # Wait indefinitely for SIGKILL
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
"""

PROCESS_B_SCRIPT = """
import os
import sys
import json
from unittest.mock import patch

# Ensure we can import core
sys.path.insert(0, sys.argv[2])

from core.accept_edits_state import load_and_reconcile_journal, set_journal_path, set_workspace_identity

def main():
    tmp_path = sys.argv[1]
    
    set_workspace_identity(tmp_path)
    jpath = os.path.join(tmp_path, "journal.jsonl")
    set_journal_path(jpath)
    
    with patch("core.accept_edits_state._atomic_write") as m_apply, \\
         patch("core.accept_edits_state._rollback_snapshot") as m_rollback, \\
         patch("os.replace") as m_replace, \\
         patch("os.unlink") as m_unlink, \\
         patch("os.remove") as m_remove:
         
        report = load_and_reconcile_journal()
        
        ops_by_id = {}
        for rec in report.operations:
            ops_by_id.setdefault(rec.operation_id, []).append(rec)
            
        classifications = {}
        for op_id, ops in ops_by_id.items():
            latest = max(ops, key=lambda r: r.sequence)
            ev = latest.event_type
            if ev == "PREPARED":
                classifications[op_id] = "PENDING_REVIEW"
            elif ev == "APPLIED":
                classifications[op_id] = "APPLIED_NOT_COMMITTED"
            elif ev == "COMMITTED":
                classifications[op_id] = "COMMITTED_NOT_RESOLVED"
            else:
                classifications[op_id] = ev
        
        out = {
            "requires_review": report.requires_review,
            "apply_count": m_apply.call_count,
            "rollback_count": m_rollback.call_count,
            "replace_count": m_replace.call_count,
            "unlink_delete_count": m_unlink.call_count + m_remove.call_count,
            "classifications": classifications,
            "diagnostics": report.diagnostics
        }
        
        print(json.dumps(out))

if __name__ == "__main__":
    main()
"""

class TestGate11FreshProcessRestart(unittest.TestCase):
    def _run_test_for_stage(self, stage: str, expected_classification: str):
        with tempfile.TemporaryDirectory() as tmp_path:
            jpath = os.path.join(tmp_path, "journal.jsonl")
            
            # Pipe for Process A to signal it reached the stage
            r, w = os.pipe()
            
            # Start Process A
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            proc_a = subprocess.Popen(
                [sys.executable, "-c", PROCESS_A_SCRIPT, stage, str(w), tmp_path, root_dir],
                pass_fds=(w,)
            )
            os.close(w)
            
            try:
                # Wait for Process A to signal
                with os.fdopen(r, "r") as f:
                    msg = f.readline().strip()
                
                self.assertEqual(msg, f"REACHED:{stage}")
                
                # Check journal exists and bytes before killing
                journal_size_before = os.path.getsize(jpath)
                
                # Kill Process A with SIGKILL
                proc_a.send_signal(signal.SIGKILL)
                proc_a.wait(timeout=5.0)
                
                # Verify SIGKILL exit
                # exit code -9 for SIGKILL on Unix
                self.assertEqual(proc_a.returncode, -signal.SIGKILL)
                
                # Start Process B
                proc_b = subprocess.run(
                    [sys.executable, "-c", PROCESS_B_SCRIPT, tmp_path, root_dir],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                # Verify Process B exit code = 0
                self.assertEqual(proc_b.returncode, 0)
                
                # Check journal bytes unchanged
                journal_size_after = os.path.getsize(jpath)
                self.assertEqual(journal_size_after, journal_size_before)
                
                # Parse RecoveryReport JSON
                report = json.loads(proc_b.stdout)
                
                # Assertions
                self.assertTrue(report["requires_review"])
                self.assertEqual(report["apply_count"], 0)
                self.assertEqual(report["rollback_count"], 0)
                self.assertEqual(report["replace_count"], 0)
                self.assertEqual(report["unlink_delete_count"], 0)
                
                op_id = "op-gate11"
                self.assertIn(op_id, report["classifications"])
                self.assertEqual(report["classifications"][op_id], expected_classification)

            finally:
                if proc_a.poll() is None:
                    proc_a.kill()
                    proc_a.wait()

    def test_prepared_fresh_restart(self):
        self._run_test_for_stage("PREPARED", "PENDING_REVIEW")

    def test_applied_fresh_restart(self):
        self._run_test_for_stage("APPLIED", "APPLIED_NOT_COMMITTED")

    def test_committed_fresh_restart(self):
        self._run_test_for_stage("COMMITTED", "COMMITTED_NOT_RESOLVED")

if __name__ == "__main__":
    unittest.main()
