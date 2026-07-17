"""Phase 4.5 — anti-frustration guards in ExecutionLoop.

Covers the three live-session fixes:
  1. web_search dedup (normalized query) → cached result, no second dispatch.
  2. file_system path jail → pre-dispatch rejection, no wasted tool call.
  3. consecutive-no-tool reasoning cap + 80% budget forced partial answer.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.loop import ExecutionLoop, _LoopCtx
from engine.state import RuntimeState
from tools.models import ToolResult
from core.parser import ToolCall


def _stub_dispatcher(per_call=None):
    """Dispatcher spy: records dispatched (tool, args) pairs."""
    calls = []

    class SpyDispatcher:
        def dispatch(self, tool_name, kwargs, timeout=30):
            calls.append((tool_name, dict(kwargs)))
            if per_call is not None:
                return per_call(tool_name, kwargs)
            return ToolResult(success=True, stdout=f"ok:{tool_name}", returncode=0)

    return SpyDispatcher(), calls


class TestWebSearchDedup(unittest.TestCase):
    def test_duplicate_query_returns_cache_without_second_dispatch(self):
        state = RuntimeState(session_id="dedup")
        spy, calls = _stub_dispatcher()
        loop = ExecutionLoop(state=state, dispatcher=spy)
        loop._ctx = _LoopCtx(user_prompt="find python 3.12 feature")

        q = "python 3.12 new feature"
        first = loop._pre_dispatch_guard(ToolCall(tool="web_search", args={"query": q}))
        self.assertIsNone(first, "first call should proceed to real dispatch")
        # Simulate the real dispatch + bookkeeping done by _dispatch_and_record_evidence.
        loop._dispatch_and_record_evidence(ToolCall(tool="web_search", args={"query": q}))

        # Second (identical, normalized) call must be short-circuited.
        dup = loop._pre_dispatch_guard(ToolCall(tool="web_search", args={"query": "  PYTHON 3.12 NEW FEATURE  "}))
        self.assertIsNotNone(dup)
        self.assertTrue(getattr(dup, "success", False))
        self.assertIn("deduped", (dup.metadata or {}))

        # The real dispatcher must have been hit exactly once.
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "web_search")

    def test_distinct_queries_both_dispatch(self):
        state = RuntimeState(session_id="dedup2")
        spy, calls = _stub_dispatcher()
        loop = ExecutionLoop(state=state, dispatcher=spy)
        loop._ctx = _LoopCtx(user_prompt="x")
        loop._dispatch_and_record_evidence(ToolCall(tool="web_search", args={"query": "alpha"}))
        g = loop._pre_dispatch_guard(ToolCall(tool="web_search", args={"query": "beta"}))
        self.assertIsNone(g)
        self.assertEqual(len(calls), 1)


class TestFileSystemPathJail(unittest.TestCase):
    def test_outside_workspace_rejected_pre_dispatch(self):
        state = RuntimeState(session_id="jail")
        spy, calls = _stub_dispatcher()
        loop = ExecutionLoop(state=state, dispatcher=spy)
        loop._ctx = _LoopCtx(user_prompt="read site-packages")

        res = loop._pre_dispatch_guard(
            ToolCall(tool="file_system", args={"action": "read", "path": "/usr/local/lib/python3.12/site-packages"})
        )
        self.assertIsNotNone(res)
        self.assertFalse(res.success)
        self.assertIn("workspace", res.stderr)
        # No real dispatch happened.
        self.assertEqual(len(calls), 0)

    def test_inside_workspace_proceeds(self):
        state = RuntimeState(session_id="jail2")
        spy, calls = _stub_dispatcher()
        loop = ExecutionLoop(state=state, dispatcher=spy)
        loop._ctx = _LoopCtx(user_prompt="read local")
        # A relative path resolves inside the pinned workspace root → allowed.
        res = loop._pre_dispatch_guard(ToolCall(tool="file_system", args={"action": "read", "path": "main.py"}))
        self.assertIsNone(res)


class TestConsecutiveNoToolCap(unittest.TestCase):
    def test_capped_rounds_force_partial_answer(self):
        state = RuntimeState(session_id="cap")
        loop = ExecutionLoop(llm_provider=MagicMock(return_value="ok"), state=state)
        loop._ctx = _LoopCtx(user_prompt="task")
        # Simulate start_time far enough in the past to be past the 80% budget
        # threshold on the time axis, so _maybe_force_partial_answer fires.
        loop._ctx.start_time = time.time() - (180 * 0.9)
        loop._safe_shutdown = MagicMock(return_value="SAFE")
        # Pre-seed one successful evidence record so the partial summary is non-empty.
        loop.evidence_log.record(tool="web_search", command_or_path="q", success=True, output_snippet="found X")

        # 3 consecutive no-tool rounds → on the 4th the cap (>3) forces partial.
        for _ in range(3):
            loop._ctx.consecutive_no_tool_rounds += 1
        forced = loop._maybe_force_partial_answer()
        self.assertTrue(forced)
        self.assertIn("Partial answer", loop._last_response)

    def test_capped_rounds_force_partial_answer_independent_of_time(self):
        state = RuntimeState(session_id="cap_notime")
        loop = ExecutionLoop(llm_provider=MagicMock(return_value="ok"), state=state)
        loop._ctx = _LoopCtx(user_prompt="task")
        loop._ctx.start_time = time.time()  # Brand new start time (time_ratio = 0)
        loop.evidence_log.record(tool="web_search", command_or_path="q", success=True, output_snippet="found X")

        loop._ctx.consecutive_no_tool_rounds = 4  # Exceeds cap (3)
        forced = loop._maybe_force_partial_answer()
        self.assertTrue(forced)
        self.assertIn("Partial answer", loop._last_response)
        self.assertIn("consecutive reasoning limit reached", loop._last_response)


class TestBudgetRecoveryMode(unittest.TestCase):
    def test_budget_recovery_time_ratio(self):
        state = RuntimeState(session_id="rec_time")
        loop = ExecutionLoop(llm_provider=MagicMock(return_value="ok"), state=state)
        loop._ctx = _LoopCtx(user_prompt="task")
        loop._ctx.consecutive_no_tool_rounds = 0
        loop._ctx.start_time = time.time() - (180 * 0.81)  # > 80% time budget
        loop.evidence_log.record(tool="file_system", command_or_path="main.py", success=True, output_snippet="code data")

        forced = loop._maybe_force_partial_answer()
        self.assertTrue(forced)
        self.assertIn("Partial answer", loop._last_response)
        self.assertIn("budget threshold reached", loop._last_response)

    def test_budget_recovery_token_ratio(self):
        state = RuntimeState(session_id="rec_tokens")
        loop = ExecutionLoop(llm_provider=MagicMock(return_value="ok"), state=state)
        loop._ctx = _LoopCtx(user_prompt="task")
        loop._ctx.consecutive_no_tool_rounds = 0
        loop._ctx.start_time = time.time()  # 0 elapsed time
        # Add messages with total content length >= 12000 * 4 * 0.8 = 38400 chars
        state.messages = [{"role": "system", "content": "x" * 40000}]
        loop.evidence_log.record(tool="search_memory", command_or_path="query", success=True, output_snippet="memory info")

        forced = loop._maybe_force_partial_answer()
        self.assertTrue(forced)
        self.assertIn("Partial answer", loop._last_response)
        self.assertIn("budget threshold reached", loop._last_response)

    def test_budget_recovery_step_ratio(self):
        state = RuntimeState(session_id="rec_steps", max_steps=10)
        state.step_count = 8  # 80% of max_steps
        loop = ExecutionLoop(llm_provider=MagicMock(return_value="ok"), state=state)
        loop._ctx = _LoopCtx(user_prompt="task")
        loop._ctx.consecutive_no_tool_rounds = 0
        loop._ctx.start_time = time.time()
        loop.evidence_log.record(tool="web_search", command_or_path="test", success=True, output_snippet="search snippet")

        forced = loop._maybe_force_partial_answer()
        self.assertTrue(forced)
        self.assertIn("Partial answer", loop._last_response)
        self.assertIn("budget threshold reached", loop._last_response)

    def test_check_budget_and_guards_hard_cap(self):
        state = RuntimeState(session_id="hard_cap")
        loop = ExecutionLoop(llm_provider=MagicMock(return_value="ok"), state=state)
        loop._ctx = _LoopCtx(user_prompt="task")
        loop._ctx.start_time = time.time() - 195  # Exceeds 180s hard ceiling
        loop.evidence_log.record(tool="web_search", command_or_path="query", success=True, output_snippet="crucial data")

        signal = loop._check_budget_and_guards()
        self.assertEqual(signal, loop._check_budget_and_guards().__class__.TERMINATE)
        self.assertIn("Partial answer", loop._last_response)
        self.assertIn("crucial data", loop._last_response)


if __name__ == "__main__":
    unittest.main()
