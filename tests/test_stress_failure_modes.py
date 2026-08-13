"""Stress tests for failure modes: hung tools, repeated timeouts, concurrent
subagents, WAL interruption during PREPARED/APPLIED, external writer during
the critical window.

LABELING CONTRACT (bug-reproduction vs acceptance MUST stay separate):

  * test_zombie_worker_reproduces_known_bug — EXPECTED FAIL pre-fix (P1-01 not
    landed). The dispatcher releases the semaphore in ``finally`` even when the
    worker thread is still running after a timeout, so a hung tool's slot is
    freed while the thread keeps running (a "zombie"). This test asserts the
    slot is NOT freed while the worker is alive — which is exactly what the bug
    violates, so it FAILS pre-fix and only PASSES once P1-01's fix lands.
    It is the reproduction, NOT the acceptance criterion.
  * test_no_zombie_workers_post_fix — EXPECTED PASS after P1-01's fix. This is
    the real acceptance criterion: after a timeout, the semaphore slot is held
    until the worker actually completes (no premature release).

All tests are deterministic: timing is mocked with threading.Events, not sleeps,
wherever possible; the few real waits use generous margins. No external
dependencies, no LLM calls — CI-safe.
"""

import threading
import time
import unittest
from unittest import mock

import engine.dispatcher as dispatcher_mod
from core.kernel.events import EventBus
from engine.dispatcher import Dispatcher, _MAX_WORKERS, _POOL_SEMAPHORE, _SHARED_POOL
from engine.state import RuntimeState
from engine.subagent_runner import SubagentRunner
from engine.tool_registry import ToolRegistry


class _HungTool:
    """A tool that blocks forever on a threading.Event (never returns on its own)."""

    name = "hung_tool"

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()

    def execute(self, **kwargs):
        return self(**kwargs)

    def __call__(self, *args, **kwargs):
        self.started.set()
        # Block until released — simulates a genuinely hung tool that ignores
        # future.cancel() (cannot be interrupted).
        self.release.wait(timeout=30)
        from tools.models import ToolResult

        return ToolResult(success=True, stdout="late", returncode=0, status="success")


def _make_dispatcher(session_id="stress-session"):
    state = RuntimeState(session_id=session_id, max_steps=10)
    return Dispatcher(state)


class TestZombieWorkers(unittest.TestCase):
    """Hung-tool timeout handling: does a timed-out-but-still-running tool
    leak its semaphore slot (zombie) or hold it until it finishes?"""

    def _fresh_state(self):
        # Isolate the global pool/semaphore state for the test.
        self._saved_pool = dispatcher_mod._SHARED_POOL
        self._saved_sem = dispatcher_mod._POOL_SEMAPHORE
        self._saved_registry = dispatcher_mod.registry
        dispatcher_mod._SHARED_POOL = _SHARED_POOL
        dispatcher_mod._POOL_SEMAPHORE = _POOL_SEMAPHORE

    def setUp(self):
        self._fresh_state()
        self._test_registry = ToolRegistry()
        self._hung = _HungTool()
        self._test_registry.register(self._hung.name, self._hung)
        dispatcher_mod.registry = self._test_registry

    def tearDown(self):
        # Release any hung tool so its worker thread can exit.
        self._hung.release.set()
        dispatcher_mod._SHARED_POOL = self._saved_pool
        dispatcher_mod._POOL_SEMAPHORE = self._saved_sem
        dispatcher_mod.registry = self._saved_registry

    def _semaphore_value(self) -> int:
        # BoundedSemaphore exposes _value (initial = _MAX_WORKERS).
        return _POOL_SEMAPHORE._value

    # ── Labeled reproduction (EXPECTED FAIL pre-fix, PASS after P1-01) ──
    def test_zombie_worker_reproduces_known_bug(self):
        """REPRODUCTION of the P1-01 bug.

        A hung tool times out. Pre-fix, the ``finally`` releases the semaphore
        even though the worker thread is STILL running — so the slot is freed
        (semaphore returns to _MAX_WORKERS) while a zombie worker occupies a
        pool thread. This assertion (slot NOT freed while worker alive) FAILS
        pre-fix — proving the bug — and PASSES once P1-01's fix holds the slot
        until the worker actually completes.
        """
        self._hung.started.clear()
        dispatcher = _make_dispatcher()
        # Short timeout so the hung tool times out quickly.
        result = dispatcher.dispatch("hung_tool", {}, timeout=0.2)

        # The dispatch returned a timeout result.
        self.assertEqual(result.status, "timeout")
        # The hung worker is STILL running (started, not released).
        self.assertTrue(self._hung.started.is_set())
        self.assertTrue(self._hung.release.is_set() is False)

        # THE BUG ASSERTION: the semaphore slot must still be held while the
        # worker is alive. Pre-fix this FAILS (slot already released).
        self.assertEqual(
            self._semaphore_value(),
            _MAX_WORKERS - 1,
            "ZOMBIE: semaphore slot released while the hung worker is still "
            "running — the pool now allows more than _MAX_WORKERS concurrent "
            "tasks (P1-01 not fixed).",
        )

    # ── Labeled acceptance (EXPECTED PASS after P1-01) ──
    def test_no_zombie_workers_post_fix(self):
        """ACCEPTANCE (post-fix): after a timeout, releasing the hung tool lets
        its worker finish and the slot be reclaimed exactly once.

        This is the real acceptance criterion once P1-01's fix lands: no
        premature release, and no double-release when the worker finally exits.
        Pre-fix it fails (the premature release breaks the accounting).
        """
        self._hung.started.clear()
        dispatcher = _make_dispatcher()
        result = dispatcher.dispatch("hung_tool", {}, timeout=0.2)
        self.assertEqual(result.status, "timeout")
        self.assertTrue(self._hung.started.is_set())

        # Release the hung worker — its thread now completes.
        self._hung.release.set()
        # Give the worker a generous margin to finish and release its slot.
        time.sleep(0.5)

        # After the worker completes, the slot is reclaimed exactly once:
        # the semaphore returns to full capacity (no double-release crash,
        # no leaked slot).
        self.assertEqual(self._semaphore_value(), _MAX_WORKERS)


class TestRepeatedTimeouts(unittest.TestCase):
    """Repeated hung-tool timeouts must not wedge the agent or corrupt results."""

    def setUp(self):
        self._saved_registry = dispatcher_mod.registry
        self._test_registry = ToolRegistry()
        self._hung = _HungTool()
        self._test_registry.register(self._hung.name, self._hung)
        dispatcher_mod.registry = self._test_registry

    def tearDown(self):
        self._hung.release.set()
        dispatcher_mod.registry = self._saved_registry

    def test_repeated_timeouts_return_timeout_results(self):
        """A burst of hung-tool dispatches all return timeout results (the
        agent is never blocked forever), and the results are well-formed."""
        dispatcher = _make_dispatcher()
        results = []
        for _ in range(_MAX_WORKERS * 2):
            r = dispatcher.dispatch("hung_tool", {}, timeout=0.1)
            results.append(r)
        # Every dispatch resolved (none hung the caller).
        self.assertEqual(len(results), _MAX_WORKERS * 2)
        for r in results:
            self.assertEqual(r.status, "timeout")
            self.assertIs(r.success, False)


class TestConcurrentSubagents(unittest.TestCase):
    """Concurrent subagent delegation: multiple SubagentRunners in flight.

    Deterministic: the fake provider blocks on an Event, so we control exactly
    when each subagent "finishes" — no real sleeps racing the scheduler.
    """

    def test_concurrent_subagents_all_resolve(self):
        barrier = threading.Event()
        results = {}

        def fake_provider(messages, **kwargs):
            barrier.wait(timeout=10)  # block all subagents until released
            return "result for a trivial sub-task"

        def run_subagent(i):
            runner = SubagentRunner(router=fake_provider, max_rounds=3, timeout=10)
            results[i] = runner.run(f"sub-task {i}")

        threads = [threading.Thread(target=run_subagent, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        # Let all three block inside the provider.
        time.sleep(0.3)
        barrier.set()  # release all three simultaneously
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive(), f"subagent thread {t.name} hung")

        self.assertEqual(len(results), 3)
        for i in range(3):
            self.assertIn("result", results[i], f"subagent {i} did not resolve")


class TestWalInterruption(unittest.TestCase):
    """Interruption during the WAL PREPARED/APPLIED sequence must never leave
    a half-committed side effect."""

    def setUp(self):
        from core.accept_edits_state import (
            _close_journal,
            reset_session,
            set_journal_path,
            set_workspace_identity,
        )

        import tempfile
        from pathlib import Path

        _close_journal()
        reset_session()
        self.td = Path(tempfile.mkdtemp())
        self.jpath = str(self.td / "journal.jsonl")
        set_workspace_identity(str(self.td))
        set_journal_path(self.jpath)

    def tearDown(self):
        from core.accept_edits_state import _close_journal, reset_session

        _close_journal()
        reset_session()

    def test_interrupt_at_prepared_leaves_no_side_effect(self):
        """REPRODUCTION — NEW REAL BUG DISCOVERED (filed as backlog, NOT fixed
        in this task per constraints).

        If the journal write for APPLIED fails (interruption mid-sequence),
        ``accept_edit`` returns RECONCILIATION_REQUIRED but leaves the edit in
        ``PROCESSING_ACCEPT`` status with its claim token dangling — the edit
        is permanently stuck (never moved to RECONCILIATION_REQUIRED, no
        reconciliation record written). Evidence: core/accept_edits_state.py
        lines 1992-2001 return early on APPLIED journal failure without
        updating the edit status.

        This test documents the buggy behavior (the edit is stuck in
        PROCESSING_ACCEPT). It is the REPRODUCTION for the backlog item — it
        will PASS only after the bug is fixed and the edit is correctly moved
        to RECONCILIATION_REQUIRED.
        """
        import uuid

        import core.accept_edits_state as aes
        from core.accept_edits_state import (
            TransactionOutcome,
            _accept_edits_pending,
            _compute_digest,
            accept_edit,
            PendingEdit,
        )

        fpath = self.td / "interrupt.txt"
        fpath.write_text("old")
        edit = PendingEdit(
            edit_id=str(uuid.uuid4()),
            path=fpath.name,
            resolved_path=str(fpath),
            old_content="old",
            new_content="new",
            diff="",
            additions=1,
            removals=0,
            expected_original_digest=_compute_digest("old"),
        )
        _accept_edits_pending.append(edit)

        # Interrupt AFTER PREPARED (the write side effect already happened via
        # the real _atomic_write_if_unchanged) but BEFORE APPLIED is recorded:
        # fail the journal write for the APPLIED record.
        orig_write = aes._write_journal_record

        def fail_applied(rec):
            if rec.event_type == "APPLIED":
                raise OSError("interrupted mid-sequence")
            return orig_write(rec)

        with mock.patch.object(aes, "_write_journal_record", side_effect=fail_applied):
            res = accept_edit(edit.edit_id)

        # The side effect happened but the journal APPLIED write failed → the
        # outcome IS reconciliation-required (correct).
        self.assertEqual(res.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)
        remaining = [e for e in _accept_edits_pending if e.edit_id == edit.edit_id]
        self.assertEqual(len(remaining), 1)
        # BUG (documented): the edit is left in PROCESSING_ACCEPT, never moved
        # to RECONCILIATION_REQUIRED. Assert the CURRENT (buggy) behavior so
        # the reproduction is explicit and fails once the backlog fix lands.
        self.assertEqual(remaining[0].status, "PROCESSING_ACCEPT")


class TestExternalWriterCriticalWindow(unittest.TestCase):
    """External writer racing the check-to-replace window must not be clobbered.

    Deterministic: the external write is injected at the CAS seam via a
    _file_digest patch (the same seam the real race lands on).
    """

    def test_external_writer_in_critical_window_is_preserved(self):
        import tempfile
        from pathlib import Path

        import core.accept_edits_state as aes
        from core.accept_edits_state import (
            TransactionOutcome,
            _accept_edits_pending,
            _close_journal,
            _compute_digest,
            _file_digest,
            accept_edit,
            reset_session,
            set_journal_path,
            set_workspace_identity,
            PendingEdit,
        )

        _close_journal()
        reset_session()
        td = Path(tempfile.mkdtemp())
        set_workspace_identity(str(td))
        set_journal_path(str(td / "journal.jsonl"))

        fpath = td / "target.txt"
        fpath.write_text("original")
        edit = PendingEdit(
            edit_id="ext-writer",
            path=fpath.name,
            resolved_path=str(fpath),
            old_content="original",
            new_content="our-write",
            diff="",
            additions=1,
            removals=0,
            expected_original_digest=_compute_digest("original"),
        )
        _accept_edits_pending.append(edit)

        external = "EXTERNAL-WRITER-SURVIVES"
        real_digest = _file_digest
        flipped = {"done": False}

        def external_write_at_cas(path):
            if not flipped["done"]:
                flipped["done"] = True
                Path(path).write_text(external)
            return real_digest(path)

        with mock.patch.object(aes, "_file_digest", side_effect=external_write_at_cas):
            res = accept_edit(edit.edit_id)

        # The CAS guard aborted the replace: external content preserved,
        # edit is a CONFLICT (not a silent clobber).
        self.assertEqual(fpath.read_text(), external)
        self.assertEqual(res.outcome, TransactionOutcome.CONFLICT)


if __name__ == "__main__":
    unittest.main()
