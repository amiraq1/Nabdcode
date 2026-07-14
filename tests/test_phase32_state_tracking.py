# tests/test_phase32_state_tracking.py
"""Phase 3.2: Explicit State Tracking & Re-dispatch Prevention."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.deep_agent import (
    NativeDeepAgent,
    DeepAgentState,
    CHECKPOINT_FILENAME,
)
from engine.state import RuntimeState
from engine.dispatcher import Dispatcher
from tools.models import ToolResult


def _stub_llm(json_response):
    def fn(messages):
        return json_response
    return fn


def _stub_dispatcher(result):
    state = RuntimeState(session_id="stub")
    class Stub(Dispatcher):
        def dispatch(self, tool_name, kwargs, timeout=30):
            return result
    return Stub(state)


class TestStateFields(unittest.TestCase):
    def test_default_cursor(self):
        s = DeepAgentState(task="t")
        self.assertEqual(s.current_node, "PLAN")
        self.assertEqual(s.current_plan_index, 0)

    def test_serialize_roundtrip(self):
        s = DeepAgentState(task="t")
        s.current_node = "EXECUTE"
        s.current_plan_index = 2
        restored = DeepAgentState.from_dict(s.to_dict())
        self.assertEqual(restored.current_node, "EXECUTE")
        self.assertEqual(restored.current_plan_index, 2)

    def test_legacy_missing_cursor_defaults(self):
        """A legacy checkpoint without cursor fields resumes safely."""
        raw = {
            "task": "legacy",
            "plan": ["a"],
            "past_steps": ["a"],
        }
        restored = DeepAgentState.from_dict(raw)
        self.assertEqual(restored.current_node, "PLAN")
        self.assertEqual(restored.current_plan_index, 0)


class TestMidExecuteRedispatchPrevention(unittest.TestCase):
    def _agent(self, llm, result):
        return NativeDeepAgent(
            runtime_state=RuntimeState(session_id="p32"),
            llm_client=llm,
            max_iterations=1,
            dispatcher=_stub_dispatcher(result),
        )

    def test_interrupted_step_not_redispatched(self):
        """A step whose result never landed (killed mid-flight) must NOT be
        blindly re-executed — it is recorded INTERRUPTED and the cursor advances."""
        agent = self._agent(
            _stub_llm('```json\n{"tool": "execute_shell", "args": {"command": "rm -rf /data"}}\n```'),
            ToolResult(success=True, stdout="would be dangerous"),
        )
        state = DeepAgentState(task="destructive")
        state.plan = ["rm -rf /data", "list files"]
        # Simulate an LMK kill: cursor parked on EXECUTE at index 0, but the
        # first step's result was NEVER recorded (past_steps empty).
        state.current_node = "EXECUTE"
        state.current_plan_index = 0
        # Mirror what run() sets on a real LMK resume so the guard fires.
        agent._resume_mode = True

        executed = []
        orig = agent.dispatcher.dispatch
        agent.dispatcher.dispatch = lambda *a, **k: executed.append(a) or orig(*a, **k)

        result_state = agent.execute_node(state)

        # The dangerous shell command must NOT have been dispatched.
        self.assertEqual(len(executed), 0, "interrupted step must not re-dispatch")
        # Step recorded as INTERRUPTED, not re-run.
        self.assertTrue(any("INTERRUPTED" in o for o in result_state.observations))
        # Cursor advanced past the interrupted step.
        self.assertEqual(result_state.current_plan_index, 1)
        # No evidence recorded for the skipped (never-run) step.
        self.assertEqual(len(agent.evidence_log.records), 0)
        # Error flag set so the loop transitions to REPLAN/REVIEW safely.
        self.assertTrue(any("LMK_INTERRUPT" in e for e in result_state.errors))

    def test_completed_step_not_redispatched_on_resume(self):
        """Steps already in past_steps (result landed) are NOT re-run on resume."""
        agent = self._agent(
            _stub_llm('```json\n{"tool": "execute_shell", "args": {"command": "wc"}}\n```'),
            ToolResult(success=True, stdout="12"),
        )
        state = DeepAgentState(task="list")
        state.plan = ["ls", "wc"]
        # Both steps completed in a prior run; cursor lagging behind them.
        state.past_steps = ["ls", "wc"]
        state.current_node = "EXECUTE"
        state.current_plan_index = 0  # lagging cursor, both steps done
        # Mirror what run() sets on a real LMK resume so the guard fires.
        agent._resume_mode = True

        executed = []
        orig = agent.dispatcher.dispatch
        agent.dispatcher.dispatch = lambda *a, **k: executed.append(a) or orig(*a, **k)

        agent.execute_node(state)

        # Neither completed step should be re-dispatched.
        self.assertEqual(len(executed), 0, "completed steps must not re-dispatch")
        self.assertEqual(state.current_plan_index, 2)


class TestGranularCheckpoint(unittest.TestCase):
    def test_checkpoint_persists_cursor(self):
        tmp = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            agent = NativeDeepAgent(
                runtime_state=RuntimeState(session_id="ckpt"),
                llm_client=_stub_llm('[]'),
                max_iterations=1,
            )
            state = DeepAgentState(task="t")
            state.plan = ["a", "b"]
            state.current_node = "EXECUTE"
            state.current_plan_index = 1
            agent._save_checkpoint(state)
            loaded = agent._load_checkpoint()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.current_node, "EXECUTE")
            self.assertEqual(loaded.current_plan_index, 1)
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
