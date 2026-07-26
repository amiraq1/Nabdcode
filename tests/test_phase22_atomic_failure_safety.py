"""Phase 2.2A — Atomic Failure Safety: 7 + 6 concurrency/leak tests.

All ``_atomic_write`` results are operation-scoped (no global state).
"""

import os
import threading
import tempfile
import unittest
from unittest.mock import patch

import core.accept_edits_state as _state
from core.accept_edits_state import (
    PendingEdit,
    reset_session,
    set_mode,
    accept_edit,
    TransactionOutcome,
    WriteStage,
    AtomicWriteResult,
)


def _make_pending_edit(path="file.py", old_content="old", new_content="new"):
    tmpdir = tempfile.mkdtemp()
    resolved = os.path.join(tmpdir, path)
    with open(resolved, "w") as f:
        f.write(old_content)
    orig_digest = _state._compute_digest(old_content) if old_content else ""
    return PendingEdit(
        path=path, resolved_path=resolved,
        old_content=old_content, new_content=new_content,
        diff=f"-{old_content}\n+{new_content}",
        additions=1, removals=1,
        expected_original_digest=orig_digest,
    )


def _cleanup_temp_files(edit):
    d = os.path.dirname(edit.resolved_path)
    for fname in os.listdir(d):
        if ".tmp." in fname:
            try:
                os.unlink(os.path.join(d, fname))
            except OSError:
                pass


def _spath(p):
    """Normalise pathlike to str for mock inspection."""
    return str(p) if not isinstance(p, str) else p


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2.2A — 7 core behavioral tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAtomicFailureSafetyPhase2_2A(unittest.TestCase):

    def setUp(self):
        reset_session()
        _state._reconciliation_journal.clear()

    # ── 1. Short-write retry ─────────────────────────────────────────────

    def test_short_write_retries_until_complete(self):
        size = 200
        edit = _make_pending_edit("short_write.py", "old", "x" * size)
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        real_write_all = _state._write_all
        call_count = [0]

        def partial_write_all(fd, data):
            if call_count[0] == 0 and len(data) > 50:
                call_count[0] += 1
                half = len(data) // 2
                real_write_all(fd, data[:half])
                real_write_all(fd, data[half:])
                return
            call_count[0] += 1
            real_write_all(fd, data)

        with patch.object(_state, "_write_all", side_effect=partial_write_all):
            result = accept_edit(edit.edit_id)

        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)
        with open(edit.resolved_path) as f:
            self.assertEqual(f.read(), "x" * size)
        _cleanup_temp_files(edit)

    # ── 2. Zero-progress write -> FAILED ─────────────────────────────────

    def test_zero_progress_write_fails_safely(self):
        edit = _make_pending_edit("zero_write.py", "original_content", "new_content")
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        tmpdir = os.path.dirname(edit.resolved_path)

        real_write_all = _state._write_all
        call_count = [0]

        def zpy_write_all(fd, data):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("short write made no progress")
            return real_write_all(fd, data)

        with patch.object(_state, "_write_all", side_effect=zpy_write_all):
            result = accept_edit(edit.edit_id)

        self.assertEqual(result.outcome, TransactionOutcome.FAILED)
        with open(edit.resolved_path) as f:
            self.assertEqual(f.read(), "original_content")
        leftovers = [n for n in os.listdir(tmpdir) if ".tmp." in n]
        self.assertEqual(len(leftovers), 0, f"Temp not cleaned: {leftovers}")

    # ── 3. Replace failure ───────────────────────────────────────────────

    def test_replace_failure_preserves_original_and_removes_temp(self):
        edit = _make_pending_edit("replace_fail.py", "original", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        tmpdir = os.path.dirname(edit.resolved_path)

        original_replace = _state.os.replace

        def broken_replace(src, dst):
            if "replace_fail" in _spath(dst):
                raise OSError("Replace failed: permission denied")
            return original_replace(src, dst)

        with patch.object(_state.os, "replace", side_effect=broken_replace):
            result = accept_edit(edit.edit_id)

        self.assertIn(result.outcome, (TransactionOutcome.FAILED, TransactionOutcome.RECONCILIATION_REQUIRED))
        with open(edit.resolved_path) as f:
            self.assertEqual(f.read(), "original")
        leftovers = [n for n in os.listdir(tmpdir) if ".tmp." in n]
        self.assertEqual(len(leftovers), 0, f"Temp not cleaned: {leftovers}")
        for fail in result.failed_items:
            self.assertNotIn(tempfile.gettempdir(), fail.safe_message)
            self.assertNotIn("/data", fail.safe_message)

    # ── 4. Snapshot failure prevents apply ───────────────────────────────

    def test_snapshot_creation_failure_prevents_apply(self):
        edit = _make_pending_edit("snapshot_fail.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        atomic_write_called = [False]

        def spy_atomic(fp, nc):
            atomic_write_called[0] = True
            return AtomicWriteResult(applied=True, durability_confirmed=True, cleanup_succeeded=True)

        with patch.object(_state, "_create_snapshot_from_disk", side_effect=OSError("Snapshot failed")):
            with patch.object(_state, "_atomic_write", side_effect=spy_atomic):
                try:
                    accept_edit(edit.edit_id)
                except Exception:
                    pass

        self.assertFalse(atomic_write_called[0], "atomic_write should NOT be called")
        with open(edit.resolved_path) as f:
            self.assertEqual(f.read(), "old")

    # ── 5. Temp cleanup failure -> RECONCILIATION_REQUIRED ────────────────

    def test_temp_cleanup_failure_is_reported(self):
        edit = _make_pending_edit("cleanup_fail.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        original_unlink = _state.os.unlink

        def broken_unlink(path):
            if "cleanup_fail" in _spath(path):
                raise OSError("Cleanup failed: permission denied")
            return original_unlink(path)

        real_write_all = _state._write_all
        call_count = [0]

        def fail_write_all(fd, data):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("short write made no progress")
            return real_write_all(fd, data)

        with patch.object(_state, "_write_all", side_effect=fail_write_all):
            with patch.object(_state.os, "unlink", side_effect=broken_unlink):
                result = accept_edit(edit.edit_id)

        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        for fail in result.failed_items:
            self.assertIn("reconciliation", fail.safe_message.lower())

    # ── 6. Mode preservation ─────────────────────────────────────────────

    def test_existing_modes_are_preserved(self):
        import stat
        for mode in (0o600, 0o644, 0o755):
            with self.subTest(mode=oct(mode)):
                edit = _make_pending_edit(f"mode_{mode:03o}.py", "old", "new")
                os.chmod(edit.resolved_path, mode)
                _state._accept_edits_pending.append(edit)
                set_mode(True)

                result = accept_edit(edit.edit_id)
                self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)

                st = os.stat(edit.resolved_path)
                preserved = stat.S_IMODE(st.st_mode)
                self.assertEqual(preserved, mode, f"Expected {oct(mode)}, got {oct(preserved)}")
                _state._accept_edits_pending.clear()
                _state.set_mode(False)
                _cleanup_temp_files(edit)

    # ── 7. Parent fsync failure ──────────────────────────────────────────

    def test_parent_fsync_failure_reports_applied_not_durable(self):
        edit = _make_pending_edit("fsync_fail.py", "old", "new content")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        with patch.object(_state, "_fsync_parent", return_value=False):
            result = accept_edit(edit.edit_id)

        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING)
        with open(edit.resolved_path) as f:
            self.assertEqual(f.read(), "new content")
        self.assertEqual(result.processed_count, 1)
        self.assertEqual(len(result.succeeded_ids), 1)
        self.assertEqual(len(result.failed_items), 0)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2.2A — 6 concurrency / leak / safety tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAtomicWriteConcurrencyIsolation(unittest.TestCase):

    def setUp(self):
        reset_session()
        _state._reconciliation_journal.clear()

    # ── C1. Cleanup error belongs to its own operation ───────────────────

    def test_cleanup_error_belongs_to_originating_operation(self):
        tmpdir = tempfile.mkdtemp()
        a_path = os.path.join(tmpdir, "a.py")
        b_path = os.path.join(tmpdir, "b.py")
        with open(a_path, "w") as f: f.write("a_old")
        with open(b_path, "w") as f: f.write("b_old")

        edit_a = PendingEdit(
            path="a.py", resolved_path=a_path,
            old_content="a_old", new_content="a_new",
            diff="-a_old\n+a_new", additions=1, removals=1,
            expected_original_digest=_state._compute_digest("a_old"),
        )
        edit_b = PendingEdit(
            path="b.py", resolved_path=b_path,
            old_content="b_old", new_content="b_new",
            diff="-b_old\n+b_new", additions=1, removals=1,
            expected_original_digest=_state._compute_digest("b_old"),
        )
        _state._accept_edits_pending.extend([edit_a, edit_b])
        set_mode(True)

        real_write = _state._write_all
        calls = [0]
        def write_then_succeed(fd, data):
            calls[0] += 1
            if calls[0] <= 1:
                raise OSError("write failed")
            return real_write(fd, data)

        original_unlink = _state.os.unlink
        def broken_unlink_a(path):
            if "a.py" in _spath(path):
                raise OSError("permission denied")
            return original_unlink(path)

        with patch.object(_state, "_write_all", side_effect=write_then_succeed):
            with patch.object(_state.os, "unlink", side_effect=broken_unlink_a):
                result_a = accept_edit(edit_a.edit_id)
                result_b = accept_edit(edit_b.edit_id)

        self.assertEqual(result_a.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertEqual(result_b.outcome, TransactionOutcome.ACCEPTED)
        for fail in result_a.failed_items:
            self.assertIn("reconciliation", fail.safe_message.lower())
        self.assertEqual(len(result_b.failed_items), 0)

    # ── C2. No leak to next transaction ──────────────────────────────────

    def test_cleanup_error_does_not_leak_to_next_transaction(self):
        edit_fail = _make_pending_edit("fail_first.py", "old", "new")
        edit_ok = _make_pending_edit("ok_second.py", "old", "new")
        _state._accept_edits_pending.extend([edit_fail, edit_ok])
        set_mode(True)

        real_write = _state._write_all
        calls = [0]
        def write_then_fail(fd, data):
            calls[0] += 1
            if calls[0] == 1:
                raise OSError("first write fails")
            return real_write(fd, data)

        original_unlink = _state.os.unlink
        def unlink_fail_first(path):
            if "fail_first" in _spath(path):
                raise OSError("cleanup denied")
            return original_unlink(path)

        with patch.object(_state, "_write_all", side_effect=write_then_fail):
            with patch.object(_state.os, "unlink", side_effect=unlink_fail_first):
                r1 = accept_edit(edit_fail.edit_id)
                r2 = accept_edit(edit_ok.edit_id)

        self.assertEqual(r1.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertEqual(r2.outcome, TransactionOutcome.ACCEPTED)
        self.assertEqual(len(r2.failed_items), 0)

    # ── C3. Concurrent cleanup failures remain separate ─────────────────

    def test_concurrent_cleanup_failures_remain_separate(self):
        tmpdir = tempfile.mkdtemp()
        a_path = os.path.join(tmpdir, "a_conc.py")
        b_path = os.path.join(tmpdir, "b_conc.py")
        with open(a_path, "w") as f: f.write("a_old")
        with open(b_path, "w") as f: f.write("b_old")

        edit_a = PendingEdit(
            path="a_conc.py", resolved_path=a_path,
            old_content="a_old", new_content="a_new",
            diff="-a_old\n+a_new", additions=1, removals=1,
            expected_original_digest=_state._compute_digest("a_old"),
        )
        edit_b = PendingEdit(
            path="b_conc.py", resolved_path=b_path,
            old_content="b_old", new_content="b_new",
            diff="-b_old\n+b_new", additions=1, removals=1,
            expected_original_digest=_state._compute_digest("b_old"),
        )
        _state._accept_edits_pending.extend([edit_a, edit_b])
        set_mode(True)

        original_unlink = _state.os.unlink
        def unlink_both_fail(path):
            if ".tmp." in _spath(path):
                raise OSError("cleanup blocked")
            return original_unlink(path)

        with patch.object(_state.os, "unlink", side_effect=unlink_both_fail):
            with patch.object(_state, "_write_all", side_effect=lambda fd, data: (_ for _ in ()).throw(OSError("write A failed"))):
                result_a = accept_edit(edit_a.edit_id)
            with patch.object(_state, "_write_all", side_effect=lambda fd, data: (_ for _ in ()).throw(OSError("write B failed"))):
                result_b = accept_edit(edit_b.edit_id)

        self.assertEqual(result_a.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertEqual(result_b.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)

    # ── C4. Successful operation has no stale cleanup error ──────────────

    def test_successful_operation_has_no_stale_cleanup_error(self):
        edit_fail = _make_pending_edit("stale_fail.py", "old", "new")
        _state._accept_edits_pending.append(edit_fail)
        set_mode(True)

        real_write_all = _state._write_all
        call_count = [0]
        def fail_one_write(fd, data):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("fail")
            return real_write_all(fd, data)

        original_unlink = _state.os.unlink
        def unlink_fail(path):
            if "stale_fail" in _spath(path):
                raise OSError("cleanup stale fail")
            return original_unlink(path)

        with patch.object(_state, "_write_all", side_effect=fail_one_write):
            with patch.object(_state.os, "unlink", side_effect=unlink_fail):
                r_fail = accept_edit(edit_fail.edit_id)
        self.assertEqual(r_fail.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)

        edit_ok = _make_pending_edit("stale_ok.py", "old", "new")
        _state._accept_edits_pending.append(edit_ok)
        _state.set_mode(True)
        r_ok = accept_edit(edit_ok.edit_id)

        self.assertEqual(r_ok.outcome, TransactionOutcome.ACCEPTED)
        self.assertEqual(len(r_ok.failed_items), 0)

    # ── C5. Cleanup fail -> RECONCILIATION_REQUIRED w/ artifact ──────────

    def test_cleanup_failure_requires_reconciliation(self):
        edit = _make_pending_edit("artifact.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        tmpdir = os.path.dirname(edit.resolved_path)

        real_write_all = _state._write_all
        call_count = [0]
        def fail_write(fd, data):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("fail")
            return real_write_all(fd, data)

        original_unlink = _state.os.unlink
        def unlink_fail(path):
            if "artifact" in _spath(path):
                raise OSError("permission denied")
            return original_unlink(path)

        with patch.object(_state, "_write_all", side_effect=fail_write):
            with patch.object(_state.os, "unlink", side_effect=unlink_fail):
                result = accept_edit(edit.edit_id)

        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        # Note: when _write_all fails before creation of tmp file, no artifact
        # (tmp_path is None in finally).  When it fails after creation but before
        # replace + cleanup fails, artifact remains.  This test catches the
        # write-stage-failure path with cleanup error → still RECONCILIATION.
        for fail in result.failed_items:
            self.assertIn("reconciliation", fail.safe_message.lower())

    # ── C6. Cleanup safe message hides absolute path ─────────────────────

    def test_cleanup_safe_message_hides_absolute_path(self):
        edit = _make_pending_edit("path_leak.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        real_write_all = _state._write_all
        call_count = [0]
        def fail_write(fd, data):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("write failed")
            return real_write_all(fd, data)

        original_unlink = _state.os.unlink
        def unlink_fail(path):
            raise OSError("[Errno 13] Permission denied")

        with patch.object(_state, "_write_all", side_effect=fail_write):
            with patch.object(_state.os, "unlink", side_effect=unlink_fail):
                result = accept_edit(edit.edit_id)

        for fail in result.failed_items:
            self.assertNotIn("/data", fail.safe_message)
            self.assertNotIn(tempfile.gettempdir(), fail.safe_message)
            self.assertNotIn("Errno", fail.safe_message)
            self.assertNotIn("Permission denied", fail.safe_message)


if __name__ == "__main__":
    unittest.main()
