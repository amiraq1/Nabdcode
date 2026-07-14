import pytest
from unittest.mock import MagicMock
from engine.state import GoalSpec, parse_goal_command, build_goal_block, RuntimeState
from engine.kinetic import KineticStateEngine
from ui.repl_termux import REPL
from engine.loop import ExecutionLoop

def test_goal_verb_precedence_over_generic():
    """Goal verbs override generic auditing verbs when goal is active"""
    kinetic = KineticStateEngine()
    kinetic._phase = "goal"
    kinetic._on_goal_set("test goal")
    assert "Pursuing Objective" in kinetic._verb
    assert kinetic._phase == "goal"

def test_repl_goal_panel_rendering():
    """REPL renders a non-transient goal panel"""
    repl = REPL(bridge=MagicMock())
    repl._loop = MagicMock()
    repl._loop.state.active_goal = GoalSpec(raw_prompt="test", success_criteria="pass")
    repl._bridge = MagicMock()
    
    result = repl._handle_goal_command("/goal test || pass")
    assert result is not None
    assert "Goal set" in result

def test_loop_injects_active_goal_into_context():
    """ExecutionLoop injects goal block into system message"""
    state = RuntimeState(session_id="test")
    state.active_goal = GoalSpec(raw_prompt="test goal", success_criteria="done")
    
    loop = ExecutionLoop(state=state, llm_provider=lambda x: "ok")
    msgs = [{"role": "system", "content": "base prompt"}]
    result = loop._inject_runtime_context(msgs)
    
    assert "<active_goal" in result[0]["content"]
    assert "test goal" in result[0]["content"]

def test_loop_goal_exit_criteria_evaluation():
    """ExecutionLoop._evaluate_goal_exit checks criteria against EvidenceLog"""
    state = RuntimeState(session_id="test")
    state.active_goal = GoalSpec(raw_prompt="test", success_criteria="test.py exists")
    
    loop = ExecutionLoop(state=state, llm_provider=lambda x: "ok")
    loop._evidence = MagicMock()
    loop._evidence.verify_fresh.return_value = True
    
    assert loop._evaluate_goal_exit() is True
    loop._evidence.verify_fresh.assert_called_once()

def test_parse_goal_simple():
    goal = parse_goal_command("/goal fix the bug")
    assert goal is not None
    assert goal.raw_prompt == "fix the bug"
    assert goal.success_criteria is None

def test_parse_goal_with_pipe_criteria():
    goal = parse_goal_command("/goal fix the bug || tests pass")
    assert goal is not None
    assert goal.raw_prompt == "fix the bug"
    assert goal.success_criteria == "tests pass"

def test_parse_goal_with_flag_criteria():
    goal = parse_goal_command("/goal fix the bug -c tests pass")
    assert goal is not None
    assert goal.raw_prompt == "fix the bug"
    assert goal.success_criteria == "tests pass"

def test_parse_goal_long_flag_criteria():
    goal = parse_goal_command("/goal fix the bug --criteria tests pass")
    assert goal is not None
    assert goal.raw_prompt == "fix the bug"
    assert goal.success_criteria == "tests pass"

def test_build_goal_block_with_criteria():
    goal = GoalSpec(raw_prompt="fix bug", success_criteria="tests pass", mode="all")
    block = build_goal_block(goal)
    assert '<active_goal intent="fix bug" mode="all">' in block
    assert '<criteria>tests pass</criteria>' in block
    assert '</active_goal>' in block

def test_build_goal_block_without_criteria():
    goal = GoalSpec(raw_prompt="just do it")
    block = build_goal_block(goal)
    assert '<active_goal intent="just do it" mode="all">' in block
    assert '<criteria>' not in block
