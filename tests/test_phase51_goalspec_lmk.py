"""Phase 5.1 — GoalSpec LMK-survival (checkpoint + resume re-injection) tests.

Verifies:
  1. DeepAgentState to_dict/from_dict fully round-trips a GoalSpec (all three
     fields, including is_met=True).
  2. The checkpoint file (.nabd_agent_state.json) carries the goal and restoring
     it yields a DeepAgentState whose .goal equals the original.
  3. On resume, run() re-injects the checkpointed GoalSpec into
     runtime_state.active_goal so the verifiable exit gate fires.
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.state import GoalSpec
from engine.deep_agent import DeepAgentState, NativeDeepAgent
from engine.state import RuntimeState
from engine.dispatcher import Dispatcher
from tools.models import ToolResult


def _stub_dispatcher(result=None):
    if result is None:
        result = ToolResult(success=True, stdout="ok")
    state = RuntimeState(session_id="g-lmk")
    class S(Dispatcher):
        def dispatch(self, t, k, timeout=30):
            return result
    return S(state)


def test_goalspec_round_trips_in_deep_agent_state():
    goal = GoalSpec(raw_prompt="ship the feature", success_criteria="tests pass", is_met=True)
    st = DeepAgentState(task="do work", goal=goal)
    d = st.to_dict()
    assert d.get("goal") is not None
    assert d["goal"]["raw_prompt"] == "ship the feature"
    assert d["goal"]["success_criteria"] == "tests pass"
    assert d["goal"]["is_met"] is True
    st2 = DeepAgentState.from_dict(d)
    assert st2.goal is not None
    assert st2.goal.raw_prompt == "ship the feature"
    assert st2.goal.success_criteria == "tests pass"
    assert st2.goal.is_met is True


def test_goalspec_none_round_trips():
    st = DeepAgentState(task="x", goal=None)
    st2 = DeepAgentState.from_dict(st.to_dict())
    assert st2.goal is None


def test_checkpoint_persists_and_restores_goal():
    """A written checkpoint file carries the goal; loading it back restores it."""
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            goal = GoalSpec(raw_prompt="verify config", success_criteria="config valid", is_met=False)
            agent = NativeDeepAgent(
                runtime_state=RuntimeState(session_id="g-ckpt"),
                llm_client=lambda m: "ok",
                dispatcher=_stub_dispatcher(),
            )
            agent.runtime_state.active_goal = goal
            st = DeepAgentState(task="verify", goal=goal)
            agent._save_checkpoint(st)

            # File exists and parses with the goal intact.
            assert agent.checkpoint_path.exists()
            restored = agent._load_checkpoint()
            assert restored is not None
            assert restored.goal is not None
            assert restored.goal.raw_prompt == "verify config"
            assert restored.goal.success_criteria == "config valid"
        finally:
            os.chdir(cwd)


def test_resume_reinjects_goal_into_runtime_state():
    """run() resume path re-injects the checkpointed GoalSpec into active_goal
    so the verifiable exit gate is enforced after an LMK kill.

    We exercise the exact resume re-injection helper (same code path run()
    calls on resume) without driving the full orchestrator loop, keeping the
    test hermetic and fast.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            runtime_state = RuntimeState(session_id="g-resume")
            agent = NativeDeepAgent(
                runtime_state=runtime_state,
                llm_client=lambda m: "ok",
                dispatcher=_stub_dispatcher(),
            )
            # Simulate a prior run that checkpointed a goal (LMK kill mid-run).
            goal = GoalSpec(raw_prompt="prove server boots", success_criteria="server responds 200", is_met=False)
            st = DeepAgentState(task="prove server boots", goal=goal)
            agent._save_checkpoint(st)

            # Operator did NOT re-issue /goal this session.
            runtime_state.active_goal = None
            # Load the checkpoint and run the SAME re-injection run() performs.
            restored = agent._load_checkpoint()
            assert restored is not None
            agent._reconcile_goal_with_checkpoint(restored)

            assert runtime_state.active_goal is not None
            assert runtime_state.active_goal.raw_prompt == "prove server boots"
            assert runtime_state.active_goal.success_criteria == "server responds 200"
        finally:
            os.chdir(cwd)


def test_resume_operator_goal_overrides_checkpoint():
    """If the operator re-issues /goal after restart, their fresh objective wins
    over the stale checkpointed one (and is written back into the state)."""
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            runtime_state = RuntimeState(session_id="g-resume2")
            agent = NativeDeepAgent(
                runtime_state=runtime_state,
                llm_client=lambda m: "ok",
                dispatcher=_stub_dispatcher(),
            )
            # Stale checkpointed goal from a previous session.
            old = GoalSpec(raw_prompt="old objective", success_criteria="old criteria")
            st = DeepAgentState(task="old objective", goal=old)
            agent._save_checkpoint(st)

            # Operator re-issued /goal this session.
            fresh = GoalSpec(raw_prompt="new objective", success_criteria="new criteria")
            runtime_state.active_goal = fresh

            restored = agent._load_checkpoint()
            agent._reconcile_goal_with_checkpoint(restored)

            # Live active_goal keeps the operator's fresh objective.
            assert runtime_state.active_goal.raw_prompt == "new objective"
            # And the checkpointed state is updated to match going forward.
            assert restored.goal.raw_prompt == "new objective"
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    for fn in [
        test_goalspec_round_trips_in_deep_agent_state,
        test_goalspec_none_round_trips,
        test_checkpoint_persists_and_restores_goal,
        test_resume_reinjects_goal_into_runtime_state,
    ]:
        fn()
        print("ok", fn.__name__)
    print("All GoalSpec LMK-survival tests passed.")
