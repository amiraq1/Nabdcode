from __future__ import annotations

from types import SimpleNamespace

from core.command_dispatcher import process_slash_command
from core.kernel.state import RuntimeState
from core.plan_apply import (
    complete_task,
    enter_plan_mode,
    record_plan,
    start_task,
    task_graph_live_status,
)


def _state_with_graph() -> RuntimeState:
    state = RuntimeState("live-task-graph")
    enter_plan_mode(state)
    record_plan(state, ["Inspect", "Verify", "Publish"])
    graph = state.task_graph
    graph.add_task("inspect", "inspect source", role="research")
    graph.add_task("verify", "verify output", role="review", depends_on=["inspect"])
    graph.add_task("publish", "publish change", role="implement", depends_on=["verify"])
    graph.add_task("independent", "independent research", role="research")
    start_task(state, "inspect", role="research")
    start_task(state, "independent", role="research")
    complete_task(state, "independent", evidence_ids=["E-live"])
    return state


def test_live_status_returns_none_without_task_graph():
    state = RuntimeState("no-graph")
    audit_before = list(state.plan_audit)

    assert task_graph_live_status(state) is None
    assert state.plan_audit == audit_before


def test_live_status_reports_active_ready_blocked_and_evidence_without_mutation():
    state = _state_with_graph()
    audit_before = list(state.plan_audit)
    snapshot_before = state.task_graph.to_dict()

    summary = task_graph_live_status(state)

    assert summary is not None
    assert "TaskGraph r1" in summary
    assert "mode=plan" in summary
    assert "active=inspect/research" in summary
    assert "ready=-" in summary
    assert "blocked=0" in summary
    assert "done=1" in summary
    assert "evidence=1" in summary
    assert state.plan_audit == audit_before
    assert state.task_graph.to_dict() == snapshot_before


def test_live_status_sanitizes_control_characters_in_task_ids():
    state = RuntimeState("live-sanitize")
    enter_plan_mode(state)
    record_plan(state, ["Inspect"])
    state.task_graph.add_task("node\x1b[31m", "inspect", role="research")

    summary = task_graph_live_status(state)

    assert "\x1b" not in summary
    assert "ready=" in summary


def test_tasks_status_command_reads_same_live_summary_without_mutation(capsys):
    state = _state_with_graph()
    audit_before = list(state.plan_audit)
    snapshot_before = state.task_graph.to_dict()

    handled = process_slash_command("/tasks status", state, SimpleNamespace(), "base")
    output = capsys.readouterr().out

    assert handled is True
    assert "[Tasks] TaskGraph r1" in output
    assert "active=inspect/research" in output
    assert "evidence=1" in output
    assert state.plan_audit == audit_before
    assert state.task_graph.to_dict() == snapshot_before
