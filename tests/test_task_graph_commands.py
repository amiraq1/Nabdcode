from __future__ import annotations

from types import SimpleNamespace

from core.command_dispatcher import process_slash_command
from core.kernel.state import RuntimeState
from core.plan_apply import enter_plan_mode, record_plan


def _run(command: str, state: RuntimeState, capsys) -> str:
    handled = process_slash_command(command, state, SimpleNamespace(), "base")
    assert handled is True
    return capsys.readouterr().out


def test_tasks_add_is_limited_to_plan_mode(capsys):
    state = RuntimeState("task-commands-mode")
    record_plan(state, ["Task graph work"])

    output = _run("/tasks add inspect research inspect workspace", state, capsys)

    assert "allowed only in PLAN mode" in output
    assert state.task_graph.to_dict()["tasks"] == []


def test_tasks_commands_drive_research_lifecycle_with_evidence(capsys):
    state = RuntimeState("task-commands-research")
    enter_plan_mode(state)
    record_plan(state, ["Inspect", "Review"])

    assert "Added inspect" in _run(
        "/tasks add inspect research inspect workspace", state, capsys
    )
    assert "Added review" in _run(
        "/tasks add review review review findings --depends inspect", state, capsys
    )
    assert "inspect: role=research" in _run("/tasks ready", state, capsys)

    assert "Started inspect" in _run("/tasks start inspect research", state, capsys)
    assert "Completed inspect" in _run("/tasks complete inspect evidence-1", state, capsys)
    ready = _run("/tasks ready", state, capsys)
    assert "review: role=review" in ready
    assert state.task_graph.get_task("inspect").evidence_ids == ("evidence-1",)
    assert state.plan_audit[-1]["event"] == "task_completed"


def test_tasks_implement_start_is_refused_without_apply(capsys):
    state = RuntimeState("task-commands-implement")
    enter_plan_mode(state)
    record_plan(state, ["Implement"])
    _run("/tasks add apply implement apply guarded change", state, capsys)

    output = _run("/tasks start apply implement", state, capsys)

    assert "Plan/Apply authorization" in output
    assert state.task_graph.get_task("apply").status.value == "ready"


def test_tasks_fail_blocks_dependents(capsys):
    state = RuntimeState("task-commands-fail")
    enter_plan_mode(state)
    record_plan(state, ["Inspect", "Review"])
    _run("/tasks add inspect research inspect workspace", state, capsys)
    _run("/tasks add review review review findings --depends inspect", state, capsys)
    _run("/tasks start inspect research", state, capsys)

    output = _run("/tasks fail inspect source unavailable", state, capsys)

    assert "Failed inspect" in output
    assert state.task_graph.get_task("inspect").status.value == "failed"
    assert state.task_graph.get_task("review").status.value == "blocked"


def test_tasks_help_and_unknown_action_are_safe(capsys):
    state = RuntimeState("task-commands-help")

    assert "Commands:" in _run("/tasks help", state, capsys)
    assert "create a Plan/Apply plan first" in _run("/tasks nonsense", state, capsys)


def test_tasks_lifecycle_transition_is_refused_outside_plan_or_apply(capsys):
    state = RuntimeState("task-commands-normal")
    enter_plan_mode(state)
    record_plan(state, ["Inspect"])
    _run("/tasks add inspect research inspect workspace", state, capsys)
    _run("/tasks start inspect research", state, capsys)
    state.operation_mode = "normal"

    output = _run("/tasks complete inspect evidence-1", state, capsys)

    assert "requires PLAN or APPLY mode" in output
    assert state.task_graph.get_task("inspect").status.value == "running"
