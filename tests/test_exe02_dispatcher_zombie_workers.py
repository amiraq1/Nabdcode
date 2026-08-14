#!/usr/bin/env python3
"""
tests/test_exe02_dispatcher_zombie_workers.py — Dispatcher Zombie Worker & Timeout Tests
========================================================================================
Validates EXE-02 requirements:
  1. Timeout does NOT release semaphore while worker thread is still alive.
  2. WorkerSlot releases semaphore exactly once on genuine worker exit (no double-release).
  3. Burst of timeouts preserves admission control boundaries (no unbounded queue buildup).
  4. Normal successful/failed executions release slots cleanly.
"""

from __future__ import annotations

import threading
import time
import unittest

from engine.dispatcher import Dispatcher, _POOL_SEMAPHORE, _WorkerSlot, get_active_worker_count
from engine.state import RuntimeState
from engine.tool_registry import registry
from tools.base import BaseTool
from tools.models import ToolResult


class _MockHungTool(BaseTool):
    """Tool that sleeps for a configurable duration to simulate a hung or slow operation."""

    name = "mock_hung_tool"
    description = "Mock hung tool for timeout testing"

    def __init__(self, sleep_seconds: float = 0.5):
        super().__init__()
        self.sleep_seconds = sleep_seconds
        self.started_event = threading.Event()
        self.completed_event = threading.Event()

    def execute(self, **kwargs) -> ToolResult:
        self.started_event.set()
        time.sleep(self.sleep_seconds)
        self.completed_event.set()
        return ToolResult(success=True, stdout="finished_eventually", returncode=0, status="success")


class _MockFastTool(BaseTool):
    """Tool that completes almost immediately."""

    name = "mock_fast_tool"
    description = "Mock fast tool"

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, stdout="fast_result", returncode=0, status="success")


class TestDispatcherZombieWorkers(unittest.TestCase):
    """Test suite for Dispatcher worker accounting and timeout isolation."""

    def setUp(self):
        self.state = RuntimeState(session_id="test_dispatcher_session")
        self.dispatcher = Dispatcher(self.state)

    def tearDown(self):
        # Allow any lingering worker threads to settle
        time.sleep(0.1)

    def test_worker_slot_releases_exactly_once(self):
        """WorkerSlot protects against double release on BoundedSemaphore."""
        sem = threading.BoundedSemaphore(1)
        sem.acquire()

        slot = _WorkerSlot(sem)
        # First release
        slot.release()
        # Second release (must be a no-op without raising ValueError)
        slot.release()
        slot.release()

        self.assertTrue(slot._released)

    def test_timeout_keeps_slot_occupied_until_worker_exits(self):
        """When a tool times out, the slot remains occupied until the worker thread exits."""
        tool = _MockHungTool(sleep_seconds=0.4)
        registry.register(tool, overwrite=True)

        start_time = time.time()
        # Dispatch with a very short timeout (0.1s)
        res = self.dispatcher.dispatch("mock_hung_tool", {}, timeout=0.1)
        duration = time.time() - start_time

        # 1. Caller got timeout result promptly
        self.assertEqual(res.status, "timeout")
        self.assertFalse(res.success)
        self.assertLess(duration, 0.3)

        # 2. Worker thread is STILL active in background, holding the slot
        self.assertTrue(tool.started_event.is_set())
        self.assertFalse(tool.completed_event.is_set())
        self.assertGreaterEqual(get_active_worker_count(), 1)

        # 3. Wait for the background worker to finish
        finished = tool.completed_event.wait(timeout=1.0)
        self.assertTrue(finished, "Worker thread should complete within 1.0s")

        # 4. Once worker finishes, active count returns to 0
        time.sleep(0.05)
        self.assertEqual(get_active_worker_count(), 0)

    def test_burst_timeouts_enforce_admission_control(self):
        """When all workers are busy executing timed-out tasks, subsequent calls fail admission control."""
        tools = [_MockHungTool(sleep_seconds=0.5) for _ in range(4)]
        for i, t in enumerate(tools):
            t.name = f"mock_hung_tool_{i}"
            registry.register(t, overwrite=True)

        fast_tool = _MockFastTool()
        registry.register(fast_tool, overwrite=True)

        # Dispatch 4 tasks in parallel, each with 0.1s timeout
        threads = []
        results = [None] * 4

        def _dispatch_task(idx):
            results[idx] = self.dispatcher.dispatch(f"mock_hung_tool_{idx}", {}, timeout=0.1)

        for i in range(4):
            th = threading.Thread(target=_dispatch_task, args=(i,))
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        # All 4 timed out
        for r in results:
            self.assertEqual(r.status, "timeout")

        # Now all 4 workers are still running in _SHARED_POOL
        # Submitting a 5th task with very short timeout should fail admission control
        res_5 = self.dispatcher.dispatch("mock_fast_tool", {}, timeout=0.05)
        self.assertEqual(res_5.status, "timeout")
        self.assertIn("workers are busy", res_5.stderr)

        # Wait for the 4 workers to finish
        for t in tools:
            t.completed_event.wait(timeout=1.0)

        time.sleep(0.05)
        self.assertEqual(get_active_worker_count(), 0)

        # Now fast tool executes normally
        res_after = self.dispatcher.dispatch("mock_fast_tool", {}, timeout=1.0)
        self.assertEqual(res_after.status, "success")

    def test_normal_execution_releases_slot_immediately(self):
        """A normal fast tool execution acquires and releases its slot immediately."""
        fast_tool = _MockFastTool()
        registry.register(fast_tool, overwrite=True)

        res = self.dispatcher.dispatch("mock_fast_tool", {}, timeout=2.0)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.stdout, "fast_result")
        self.assertEqual(get_active_worker_count(), 0)


if __name__ == "__main__":
    unittest.main()
