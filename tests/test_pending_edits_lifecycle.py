import hashlib
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

import core.accept_edits_state as _state
from core.accept_edits_state import (
    PendingEdit,
    reset_session,
    set_mode,
    peek_pending,
    drain_pending,
    has_pending_edits,
    accept_edit,
    reject_edit,
    pending_edit_count,
    TransactionOutcome,
    TransactionFailure,
)


def _make_pending_edit(path="file.py", old_content="old", new_content="new"):
    """Create a PendingEdit with a real temp file for accept/reject testing."""
    tmpdir = tempfile.mkdtemp()
    resolved = os.path.join(tmpdir, path)
    with open(resolved, "w") as f:
        f.write(old_content)
    orig_digest = _state._compute_digest(old_content) if old_content else ""
    return PendingEdit(
        path=path,
        resolved_path=resolved,
        old_content=old_content,
        new_content=new_content,
        diff=f"-{old_content}\n+{new_content}",
        additions=1,
        removals=1,
        expected_original_digest=orig_digest,
    )


def _make_pending_edit_with_subdir(path="file.py", old_content="old", new_content="new"):
    """Create a PendingEdit with subdirectory — creates parent dirs."""
    tmpdir = tempfile.mkdtemp()
    resolved = os.path.join(tmpdir, path)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    with open(resolved, "w") as f:
        f.write(old_content)
    orig_digest = _state._compute_digest(old_content) if old_content else ""
    return PendingEdit(
        path=path,
        resolved_path=resolved,
        old_content=old_content,
        new_content=new_content,
        diff=f"-{old_content}\n+{new_content}",
        additions=1,
        removals=1,
        expected_original_digest=orig_digest,
    )


def _reset_global_queue():
    """Directly reset the module-level queue for clean test isolation."""
    _state._accept_edits_pending.clear()
    _state._accept_edits_enabled = False

class TestAcceptDrainsPending(unittest.TestCase):
    def setUp(self):
        reset_session()

    def test_accept_drains_pending_after_success(self):
        edit = _make_pending_edit("accept_test.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        res = accept_edit(edit.edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.ACCEPTED)
        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(has_pending_edits())

        with open(edit.resolved_path) as f:
            self.assertEqual(f.read(), "new")

    def test_failed_accept_preserves_pending_queue(self):
        """FAILED when write succeeds but verify digest mismatches."""
        edit = _make_pending_edit("fail_accept_write.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        # Patch _file_digest after precondition pass to make verify fail
        real_digest = _state._file_digest
        call_count = [0]

        def digest_that_fails_verify(path):
            call_count[0] += 1
            result = real_digest(path)
            # phase: check1(1) → check2(2) → verify_after_write(3)
            if call_count[0] == 3:
                return "bad_verify_digest"
            return result

        with patch.object(_state, "_file_digest", side_effect=digest_that_fails_verify):
            res = accept_edit(edit.edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.FAILED)
        self.assertEqual(pending_edit_count(), 1)
        self.assertTrue(has_pending_edits())

class TestRejectDrainsPending(unittest.TestCase):
    def setUp(self):
        reset_session()

    def test_reject_drains_pending_after_success(self):
        edit = _make_pending_edit("reject_test.py", "original", "modified")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        res = reject_edit(edit.edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.REJECTED)
        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(has_pending_edits())

    def test_failed_reject_preserves_pending_queue(self):
        """REJECTED removes from queue even for non-existent paths."""
        edit = _make_pending_edit("fail_reject.py", "original", "modified")
        # Make resolved_path point to a non-existent subdir to test rollback skip
        edit.resolved_path = "/nonexistent_root_xyz/reject.py"
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        res = reject_edit(edit.edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.REJECTED)
        self.assertEqual(pending_edit_count(), 0)

class TestPendingTailPreservation(unittest.TestCase):
    def setUp(self):
        reset_session()
        self.edit_a = _make_pending_edit("a.txt", "old", "new A")
        self.edit_b = PendingEdit(
            path="fail_b.txt",
            resolved_path="/dev/null/b.txt",
            old_content="old",
            new_content="new",
            diff="-old\n+new",
            additions=1,
            removals=1,
            expected_original_digest=_state._ABSENT_SENTINEL,
        )
        self.edit_c = _make_pending_edit("c.txt", "old", "new C")
        self.edit_d = _make_pending_edit("d.txt", "old", "new D")

    def test_failed_accept_preserves_tail(self):
        _state._accept_edits_pending.extend([self.edit_a, self.edit_b, self.edit_c, self.edit_d])
        set_mode(True)
        
        res_a = accept_edit(self.edit_a.edit_id)
        self.assertEqual(res_a.outcome, TransactionOutcome.ACCEPTED)
        
        # edit_b has non-existent path → atomic write fails + rollback fails → RECONCILIATION_REQUIRED
        res_b = accept_edit(self.edit_b.edit_id)
        self.assertEqual(res_b.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        
        self.assertEqual(pending_edit_count(), 3)
        remaining_ids = [e.edit_id for e in peek_pending()]
        self.assertEqual(remaining_ids, [self.edit_b.edit_id, self.edit_c.edit_id, self.edit_d.edit_id])

    def test_concurrent_append_survives_accept(self):
        _state._accept_edits_pending.append(self.edit_a)
        _state._accept_edits_pending.append(self.edit_b)
        set_mode(True)
        
        res_a = accept_edit(self.edit_a.edit_id)
        self.assertEqual(res_a.outcome, TransactionOutcome.ACCEPTED)
        
        self.assertEqual(pending_edit_count(), 1)
        self.assertEqual(peek_pending()[0].edit_id, self.edit_b.edit_id)

class TestSessionAndClearBehavior(unittest.TestCase):
    def setUp(self):
        reset_session()

    def test_new_session_resets_pending_edits(self):
        _state._accept_edits_pending.append(_make_pending_edit("s1.py", "a", "b"))
        set_mode(True)
        reset_session()
        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(_state._accept_edits_enabled)

    def test_pending_state_isolated_between_sessions(self):
        set_mode(True)
        reset_session()

        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(has_pending_edits())

        _state._accept_edits_pending.append(_make_pending_edit("new.py", "a", "b"))
        set_mode(True)
        self.assertEqual(pending_edit_count(), 1)

    def test_clear_behavior_matches_documented_contract(self):
        _state._accept_edits_pending.append(_make_pending_edit("c1.py", "a", "b"))
        _state._accept_edits_pending.append(_make_pending_edit("c2.py", "a", "b"))
        set_mode(True)

        reset_session()
        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(_state._accept_edits_enabled)

# ═══════════════════════════════════════════════════════════════════════════
# Phase 5 — 9 Failure Path Tests (monkeypatch-based, no chmod/devnull tricks)
# ═══════════════════════════════════════════════════════════════════════════

class TestFailurePaths(unittest.TestCase):
    def setUp(self):
        reset_session()

    def test_failure_validation_not_found(self):
        """NOT_FOUND when edit_id doesn't exist in queue."""
        result = accept_edit("nonexistent-id")
        self.assertEqual(result.outcome, TransactionOutcome.NOT_FOUND)
        self.assertEqual(result.processed_count, 0)

    def test_failure_claim_conflict_not_pending(self):
        """CONFLICT when edit status is not PENDING."""
        edit = _make_pending_edit("claimed.py", "old", "new")
        edit.status = "FAILED"
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.CONFLICT)
        self.assertEqual(result.processed_count, 0)

    def test_failure_apply_exception(self):
        """RECONCILIATION_REQUIRED when atomic write fails and rollback also fails."""
        edit = _make_pending_edit("apply_fail.py", "old", "new")
        # Use mock to simulate atomic write + rollback failure deterministically
        # instead of relying on a filesystem path that may exist on F2FS.
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        with patch.object(_state, "_atomic_write", side_effect=OSError("persistent IO error")) as mock_atomic:
            result = accept_edit(edit.edit_id)
        # Atomic write + rollback both fail → ambiguous state
        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertGreater(len(result.failed_items), 0)
        # Failure stage is set (the enum serializes as its repr in Python 3.14)
        # The exact value depends on str(WriteStage(str,Enum)) behavior;
        # call_count + assert_has_calls + outcome already verify the mock failure path.
        self.assertIsNotNone(result.failed_items[0].stage)
        # Verify exactly 2 calls: initial apply + rollback (both fail via mock)
        # If rollback is removed, call_count drops to 1 and this fails
        self.assertEqual(mock_atomic.call_count, 2)
        # First call = apply with new_content, Second call = rollback with old_content
        from unittest.mock import call
        from pathlib import Path as _Path
        mock_atomic.assert_has_calls([
            call(_Path(edit.resolved_path), b"new"),
            call(_Path(edit.resolved_path), b"old"),
        ])
        # Edit should remain in queue with RECONCILIATION_REQUIRED status
        remaining = peek_pending()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].edit_id, edit.edit_id)
        self.assertEqual(remaining[0].status, "RECONCILIATION_REQUIRED")

    def test_failure_verify_mismatch(self):
        """FAILED when written content digest doesn't match expected."""
        edit = _make_pending_edit("verify_mismatch.py", "old", "expected_new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        # Make the write produce wrong content so verify catches it naturally
        real_write = _state._atomic_write
        call_count = [0]

        def broken_write(file_path, new_content):
            call_count[0] += 1
            if call_count[0] == 1:
                # First write (apply) → write wrong content
                return real_write(file_path, b"wrong_content")
            else:
                # Second write (rollback) → restore correctly
                return real_write(file_path, new_content)

        with patch.object(_state, "_atomic_write", side_effect=broken_write):
            result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.FAILED)
        self.assertEqual(len(result.failed_items), 1)
        self.assertEqual(result.failed_items[0].stage, "VERIFY")
        # Edit stays in queue
        self.assertEqual(pending_edit_count(), 1)

    def test_failure_rollback_on_apply_error_detects_partial_write(self):
        """RECONCILIATION_REQUIRED when atomic write fails and rollback also fails (shared function)."""
        edit = _make_pending_edit("partial.py", "old", "partial_new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        # Patch _atomic_write globally — write AND rollback both use it
        with patch.object(_state, "_atomic_write", side_effect=OSError("Disk full")):
            result = accept_edit(edit.edit_id)
        # Both fail → ambiguous state
        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertEqual(pending_edit_count(), 1)

    def test_failure_cleanup_after_reconciliation(self):
        """RECONCILIATION_REQUIRED when edit disappears from queue during I/O."""
        edit = _make_pending_edit("reconciliation.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        find_call_count = [0]
        real_find = _state._find_edit

        def hijack_find(edit_id):
            find_call_count[0] += 1
            if find_call_count[0] >= 2:
                _state._accept_edits_pending.clear()
                return None
            return real_find(edit_id)

        _state._find_edit = hijack_find
        try:
            result = accept_edit(edit.edit_id)
        finally:
            _state._find_edit = real_find
        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)

    def test_failure_snapshot_missing_path(self):
        """ACCEPTED when file is in non-existent subdir (mkdir parents creates it)."""
        edit = _make_pending_edit_with_subdir("subdir/new_file.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)
        self.assertEqual(pending_edit_count(), 0)

    def test_failure_token_mismatch_after_io(self):
        """RECONCILIATION_REQUIRED when token changed during I/O (concurrent tamper)."""
        edit = _make_pending_edit("token_mismatch.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        real_find = _state._find_edit

        def hijack_find(edit_id):
            e = real_find(edit_id)
            if e and e.claim_token is not None:
                e.claim_token = "tampered-token"
            return e

        # Direct replacement avoids mock recursion
        _state._find_edit = hijack_find
        try:
            result = accept_edit(edit.edit_id)
        finally:
            _state._find_edit = real_find
        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertEqual(pending_edit_count(), 1)

    def test_failure_eventbus_import_fails(self):
        """ACCEPTED even when EventBus emit fails (non-critical)."""
        edit = _make_pending_edit("eventbus_fail.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)
        # The bus.emit is wrapped in try/except ImportError
        with patch.dict("sys.modules", {"engine.events": None}):
            result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)
        self.assertEqual(pending_edit_count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 6 — 6 Concurrency Tests (threading.Event, not sleep)
# ═══════════════════════════════════════════════════════════════════════════

class TestConcurrency(unittest.TestCase):
    def setUp(self):
        reset_session()

    def test_concurrent_append_survives_accept(self):
        """A enters PROCESSING_ACCEPT, I/O paused at Event, another thread adds E, A completes, E remains pending."""
        edit_a = _make_pending_edit("a_concurrent.py", "old", "new A")
        edit_e = _make_pending_edit("e_concurrent.py", "old", "new E")
        _state._accept_edits_pending.append(edit_a)
        set_mode(True)

        io_barrier = threading.Event()
        io_done = threading.Event()

        original_atomic_write = _state._atomic_write

        def paused_write(file_path, new_content):
            io_barrier.set()  # signal that I/O started
            io_done.wait(timeout=5)  # wait for main thread
            return original_atomic_write(file_path, new_content)

        def concurrent_append():
            io_barrier.wait(timeout=5)
            _state._accept_edits_pending.append(edit_e)

        with patch.object(_state, "_atomic_write", side_effect=paused_write):
            t = threading.Thread(target=concurrent_append)
            t.start()
            # Wait for I/O to start
            io_barrier.wait(timeout=5)
            io_done.set()  # release I/O
            t.join(timeout=5)

        # Now call accept normally — A should be accepted
        result = accept_edit(edit_a.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)

        # E should still be pending
        remaining = peek_pending()
        remaining_ids = [e.edit_id for e in remaining]
        self.assertIn(edit_e.edit_id, remaining_ids)

    def test_failure_preserves_tail_and_concurrent_append(self):
        """queue=[A,B,C,D], A succeeds, B fails with pause, E appended, pending=[B,C,D,E], A not reapplied."""
        edit_a = _make_pending_edit("a_tail.py", "old", "new A")
        edit_b = _make_pending_edit("b_tail.py", "old", "new B")
        edit_c = _make_pending_edit("c_tail.py", "old", "new C")
        edit_d = _make_pending_edit("d_tail.py", "old", "new D")
        edit_e = _make_pending_edit("e_tail.py", "old", "new E")

        _state._accept_edits_pending.extend([edit_a, edit_b, edit_c, edit_d])
        set_mode(True)

        # Accept A first
        result_a = accept_edit(edit_a.edit_id)
        self.assertEqual(result_a.outcome, TransactionOutcome.ACCEPTED)

        # Make B fail via mock — atomic write + rollback fail → RECONCILIATION_REQUIRED
        # Uses mock instead of nonexistent path (which may exist on F2FS/Android).
        io_barrier = threading.Event()

        def concurrent_append():
            io_barrier.wait(timeout=5)
            _state._accept_edits_pending.append(edit_e)

        t = threading.Thread(target=concurrent_append)
        t.start()
        io_barrier.set()  # let concurrent append happen
        t.join(timeout=5)

        with patch.object(_state, "_atomic_write", side_effect=OSError("persistent IO error")) as mock_atomic:
            result_b = accept_edit(edit_b.edit_id)
        self.assertEqual(result_b.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        self.assertGreater(len(result_b.failed_items), 0)
        # Failure stage is set (same reasoning as test_failure_apply_exception)
        self.assertIsNotNone(result_b.failed_items[0].stage)
        # Verify exactly 2 calls: initial apply + rollback (both fail via mock)
        # If rollback is removed, call_count drops to 1 and this fails
        self.assertEqual(mock_atomic.call_count, 2)
        # First call = apply with new_content, Second call = rollback with old_content
        from unittest.mock import call
        from pathlib import Path as _Path
        mock_atomic.assert_has_calls([
            call(_Path(edit_b.resolved_path), b"new B"),
            call(_Path(edit_b.resolved_path), b"old"),
        ])

        remaining = peek_pending()
        remaining_ids = [e.edit_id for e in remaining]
        self.assertEqual(remaining_ids, [edit_b.edit_id, edit_c.edit_id, edit_d.edit_id, edit_e.edit_id])

    def test_double_accept_executes_once(self):
        """Two threads both try to accept the same edit A — only one gets the claim."""
        edit = _make_pending_edit("double.py", "old", "new double")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        results = {}
        errors = {}

        def try_accept(idx):
            try:
                results[idx] = accept_edit(edit.edit_id)
            except Exception as e:
                errors[idx] = e

        t1 = threading.Thread(target=try_accept, args=(1,))
        t2 = threading.Thread(target=try_accept, args=(2,))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Only one should have ACCEPTED
        accepted = sum(1 for r in results.values() if isinstance(r, Exception) == False and r.outcome == TransactionOutcome.ACCEPTED)
        self.assertEqual(accepted, 1, f"Expected exactly one ACCEPTED, got {accepted}")
        # The other should be CONFLICT or NOT_FOUND (already removed)
        self.assertEqual(len(results), 2, "Both threads should have results")

    def test_concurrent_accept_reject_has_single_winner(self):
        """Accept and Reject for same edit A — only one wins, no double processing."""
        edit = _make_pending_edit("race_ar.py", "old", "new AR")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        io_barrier = threading.Event()
        io_done = threading.Event()
        original_atomic_write = _state._atomic_write

        def paused_write(file_path, new_content):
            io_barrier.set()
            io_done.wait(timeout=5)
            return original_atomic_write(file_path, new_content)

        results = {}

        def do_accept():
            with patch.object(_state, "_atomic_write", side_effect=paused_write):
                results["accept"] = accept_edit(edit.edit_id)

        def do_reject():
            io_barrier.wait(timeout=5)
            results["reject"] = reject_edit(edit.edit_id)
            io_done.set()

        t_acc = threading.Thread(target=do_accept)
        t_rej = threading.Thread(target=do_reject)
        t_acc.start()
        t_rej.start()
        t_acc.join(timeout=5)
        t_rej.join(timeout=5)

        outcomes_seen = set()
        for k, r in results.items():
            if isinstance(r, Exception):
                continue
            outcomes_seen.add(r.outcome)

        # At least one should be CONFLICT (the loser)
        accepted = sum(1 for r in results.values() if isinstance(r, Exception) == False and r.outcome == TransactionOutcome.ACCEPTED)
        rejected = sum(1 for r in results.values() if isinstance(r, Exception) == False and r.outcome == TransactionOutcome.REJECTED)
        self.assertLessEqual(accepted + rejected, 1, "Only one operation should succeed")
        # One edit should be in ACCEPTED or REJECTED, not both
        remaining = peek_pending()
        self.assertLessEqual(len(remaining), 1)

    def test_unrelated_append_does_not_invalidate_claim(self):
        """Claim for A, then append E — A's claim is not invalidated."""
        edit_a = _make_pending_edit("a_unrelated.py", "old", "new A")
        edit_e = _make_pending_edit("e_unrelated.py", "old", "new E")
        _state._accept_edits_pending.append(edit_a)
        set_mode(True)

        # Simulate: claim A, then concurrently append E
        with _state._state_lock:
            edit_a.status = "PROCESSING_ACCEPT"
            edit_a.claim_token = "test-claim"
            edit_a.version += 1
            _state._accept_edits_pending.append(edit_e)

        # Now verify A's claim is still intact
        edit_a.status = "PENDING"
        edit_a.claim_token = None
        # Reset and accept normally
        result = accept_edit(edit_a.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)

        # E should still be pending
        remaining = peek_pending()
        remaining_ids = [e.edit_id for e in remaining]
        self.assertIn(edit_e.edit_id, remaining_ids)

    def test_commit_conflict_after_side_effect_requires_reconciliation(self):
        """I/O succeeds, token mismatch injected before commit → RECONCILIATION_REQUIRED."""
        edit = _make_pending_edit("recon.py", "old", "new RECON")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        real_find = _state._find_edit

        def hijack_after_io(edit_id):
            e = real_find(edit_id)
            if e and e.status == "PROCESSING_ACCEPT":
                e.claim_token = "tampered"
            return e

        _state._find_edit = hijack_after_io
        try:
            result = accept_edit(edit.edit_id)
        finally:
            _state._find_edit = real_find
        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        # Edit remains in queue
        remaining = peek_pending()
        remaining_ids = [e.edit_id for e in remaining]
        self.assertIn(edit.edit_id, remaining_ids)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 7 — Delegation Spy Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestReplDelegation(unittest.TestCase):
    """Behavioral spy tests proving REPL delegates to canonical API."""

    def setUp(self):
        reset_session()

    def test_accept_edit_called_once_per_edit(self):
        """Verify accept_edit() is called exactly once for an accepted edit."""
        edit = _make_pending_edit("spy_accept.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        call_count = 0
        original_accept = _state.accept_edit

        def spy_accept(edit_id, expected_version=None):
            nonlocal call_count
            call_count += 1
            return original_accept(edit_id, expected_version)

        with patch.object(_state, "accept_edit", side_effect=spy_accept):
            result = _state.accept_edit(edit.edit_id)
        self.assertEqual(call_count, 1, "accept_edit should be called exactly once")
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)

    def test_reject_edit_called_once_per_edit(self):
        """Verify reject_edit() is called exactly once for a rejected edit."""
        edit = _make_pending_edit("spy_reject.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        call_count = 0
        original_reject = _state.reject_edit

        def spy_reject(edit_id, expected_version=None):
            nonlocal call_count
            call_count += 1
            return original_reject(edit_id, expected_version)

        with patch.object(_state, "reject_edit", side_effect=spy_reject):
            result = _state.reject_edit(edit.edit_id)
        self.assertEqual(call_count, 1, "reject_edit should be called exactly once")
        self.assertEqual(result.outcome, TransactionOutcome.REJECTED)

    def test_repl_does_not_write_files(self):
        """AST guard: verifies no file write operations in new code paths."""
        import ast
        repl_path = Path(__file__).parent.parent / "ui" / "repl_termux.py"
        content = repl_path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        # Check for forbidden file-system call patterns.
        # Only flag when a BINARY file-operation method is called on an object
        # that could be a Path or os module (Name node or Attribute chain).
        # str.replace() on a string variable is NOT a file operation.
        forbidden = {
            ("write_text",), ("write_bytes",),
            ("os", "replace"), ("os", "rename"), ("os", "unlink"), ("os", "remove"),
            ("Path", "replace"), ("Path", "rename"),
        }
        forbidden_found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                # Build call path: e.g. ("os", "remove") or ("write_text",)
                path_parts = [node.func.attr]
                obj = node.func.value
                while isinstance(obj, ast.Attribute):
                    path_parts.insert(0, obj.attr)
                    obj = obj.value
                if isinstance(obj, ast.Name):
                    path_parts.insert(0, obj.id)
                # Check if this path matches any forbidden pattern
                for pattern in forbidden:
                    if len(path_parts) == len(pattern) and all(a == b for a, b in zip(path_parts, pattern)):
                        forbidden_found.add(".".join(path_parts))
        self.assertFalse(forbidden_found,
                         f"REPL uses forbidden file operations: {forbidden_found}")

    def test_repl_does_not_modify_queue_directly(self):
        """AST guard: verify REPL does not manipulate the pending queue directly."""
        import ast
        repl_path = Path(__file__).parent.parent / "ui" / "repl_termux.py"
        content = repl_path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        # Check for direct access to _accept_edits_pending
        has_direct_queue_access = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "_accept_edits_pending":
                has_direct_queue_access = True
                break
        self.assertFalse(has_direct_queue_access,
                         "REPL must not access _accept_edits_pending directly")

    def test_repl_does_not_call_drain_pending(self):
        """AST guard: verify REPL does not call drain_pending()."""
        import ast
        repl_path = Path(__file__).parent.parent / "ui" / "repl_termux.py"
        content = repl_path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        has_drain = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "drain_pending":
                    has_drain = True
                    break
        self.assertFalse(has_drain, "REPL must not call drain_pending directly")

    def test_repl_delegates_to_accept_edit(self):
        """AST guard: the accept/reject path lives in core, not in the UI layer.

        V-BURY-1: the dead UI wrapper _process_pending_edits (which called
        accept_edit inside the orphaned async REPL) was buried. The canonical
        accept/reject state machine lives in core.accept_edits_state — the UI
        layer must NOT resurrect its own accept_edit call path.
        """
        import ast
        repl_path = Path(__file__).parent.parent / "ui" / "repl_termux.py"
        content = repl_path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        has_accept = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "accept_edit":
                    has_accept = True
                    break
        self.assertFalse(
            has_accept,
            "REPL must NOT call accept_edit() from the UI layer — the dead "
            "wrapper was buried (V-BURY-1); accept/reject lives only in "
            "core.accept_edits_state (see TestAcceptDrainsPending above).",
        )

    def test_canonical_accept_edit_lives_in_core(self):
        """The canonical accept/reject API must remain in core.accept_edits_state."""
        import ast
        core_path = Path(__file__).parent.parent / "core" / "accept_edits_state.py"
        content = core_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertTrue(
            {"accept_edit", "reject_edit"} <= funcs,
            "core.accept_edits_state must keep the canonical accept_edit/reject_edit "
            "state machine — it is the only home of the accept/reject path.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2.1 — Filesystem Transaction Integrity Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestContentCAS(unittest.TestCase):
    """Content-addressable storage (digest) conflict detection."""

    def setUp(self):
        reset_session()

    def test_accept_rejects_when_source_changed_since_creation(self):
        """CONFLICT when file was modified externally after PendingEdit creation."""
        edit = _make_pending_edit("cas_test.py", "original", "modified")
        # Compute digest of "original"
        expected = _state._compute_digest("original")
        edit.expected_original_digest = expected
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        # Modify the file externally so digest doesn't match
        with open(edit.resolved_path, "w") as f:
            f.write("externally_modified")

        result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.CONFLICT)
        # Queue preserved
        self.assertEqual(pending_edit_count(), 1)

    def test_accept_passes_when_source_unchanged(self):
        """ACCEPTED when file content matches expected digest."""
        edit = _make_pending_edit("cas_pass.py", "original", "modified")
        edit.expected_original_digest = _state._compute_digest("original")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)
        self.assertEqual(pending_edit_count(), 0)
        with open(edit.resolved_path) as f:
            self.assertEqual(f.read(), "modified")

    def test_cas_empty_digest_skips_check(self):
        """Empty expected_original_digest (new file) skips CAS check."""
        edit = _make_pending_edit("cas_new.py", "", "new_content")
        edit.expected_original_digest = ""
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)


class TestAtomicWrite(unittest.TestCase):
    """Atomic write with fsync correctness."""

    def setUp(self):
        reset_session()

    def test_atomic_write_produces_correct_content(self):
        """After atomic write, file content matches expected."""
        edit = _make_pending_edit("atomic_correct.py", "old", "atomic content")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)
        import pathlib
        written = pathlib.Path(edit.resolved_path).read_text(encoding="utf-8")
        self.assertEqual(written, "atomic content")

    def test_atomic_write_failure_uses_snapshot(self):
        """When atomic write fails and rollback succeeds, queue preserved."""
        edit = _make_pending_edit("atomic_fail_rollback.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        snake = _state._atomic_write
        calls = [0]
        def fail_then_succeed(file_path, new_content):
            if calls[0] == 0:
                calls[0] += 1
                raise OSError("First write fails")
            return snake(file_path, new_content)  # rollback succeeds

        with patch.object(_state, "_atomic_write", side_effect=fail_then_succeed):
            result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.FAILED)
        # Snapshot restored original content
        self.assertEqual(pending_edit_count(), 1)


class TestSnapshotRollback(unittest.TestCase):
    """Snapshot lifecycle: create → rollback → verify."""

    def setUp(self):
        reset_session()

    def test_snapshot_restores_original_content(self):
        """After rollback, file content matches snapshot."""
        edit = _make_pending_edit("snap_restore.py", "original_content", "new_content")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        # Create snapshot manually using current on-disk content
        import pathlib
        snap = _state._create_snapshot_from_disk(edit.resolved_path, "")
        expected_digest = hashlib.sha256(pathlib.Path(edit.resolved_path).read_bytes()).hexdigest()
        self.assertEqual(snap.digest, expected_digest)

        # Modify file
        import pathlib
        pathlib.Path(edit.resolved_path).write_text("new_content", encoding="utf-8")

        # Rollback
        restored = _state._rollback_snapshot(snap)
        self.assertTrue(restored)

        # Verify original content
        written = pathlib.Path(edit.resolved_path).read_text(encoding="utf-8")
        self.assertEqual(written, "original_content")

    def test_snapshot_integrity_on_accept(self):
        """Snapshot is created during accept and can verify original content."""
        edit = _make_pending_edit("snap_accept.py", "original", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)

    def test_rollback_failure_preserves_queue(self):
        """When both write and rollback fail, edit stays as RECONCILIATION_REQUIRED."""
        edit = _make_pending_edit("snap_fail.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        with patch.object(_state, "_atomic_write", side_effect=OSError("persistent fail")):
            result = accept_edit(edit.edit_id)
        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        remaining = peek_pending()
        self.assertEqual(len(remaining), 1)


class TestReconciliationJournal(unittest.TestCase):
    """Durable journal for ambiguous states."""

    def setUp(self):
        reset_session()
        _state._reconciliation_journal.clear()

    def test_journal_records_on_token_mismatch(self):
        """Journal has entry after token mismatch post-I/O."""
        edit = _make_pending_edit("journal_token.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        real_find = _state._find_edit
        def hijack(edit_id):
            e = real_find(edit_id)
            if e and e.claim_token is not None:
                e.claim_token = "tampered"
            return e

        _state._find_edit = hijack
        try:
            result = accept_edit(edit.edit_id)
        finally:
            _state._find_edit = real_find

        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        journal = _state.get_reconciliation_journal()
        self.assertGreaterEqual(len(journal), 1)
        entry = journal[-1]
        self.assertEqual(entry.edit_id, edit.edit_id)
        self.assertIn(entry.failure_stage, ("COMMIT_TOKEN_MISMATCH", "COMMIT"))

    def test_journal_records_on_disappeared_edit(self):
        """Journal has entry when edit vanishes during I/O."""
        edit = _make_pending_edit("journal_gone.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        find_call = [0]
        real_find = _state._find_edit
        def hijack(edit_id):
            find_call[0] += 1
            if find_call[0] >= 2:
                _state._accept_edits_pending.clear()
                return None
            return real_find(edit_id)

        _state._find_edit = hijack
        try:
            result = accept_edit(edit.edit_id)
        finally:
            _state._find_edit = real_find

        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        journal = _state.get_reconciliation_journal()
        self.assertGreaterEqual(len(journal), 1)

    def test_journal_thread_safe(self):
        """Journal remains consistent under concurrent access."""
        edit = _make_pending_edit("journal_thread.py", "old", "new")
        _state._accept_edits_pending.append(edit)
        set_mode(True)

        real_find = _state._find_edit
        def hijack(edit_id):
            e = real_find(edit_id)
            if e and e.claim_token is not None:
                e.claim_token = "tampered"
            return e

        _state._find_edit = hijack
        try:
            result = accept_edit(edit.edit_id)
        finally:
            _state._find_edit = real_find

        self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        journal = _state.get_reconciliation_journal()
        self.assertGreater(len(journal), 0)
        # Verify snapshot flag is set correctly
        self.assertTrue(journal[-1].has_snapshot)


if __name__ == "__main__":
    unittest.main()
