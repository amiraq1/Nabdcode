from __future__ import annotations

import json
from types import SimpleNamespace

from core.kernel.state import RuntimeState
from core.plan_apply import enter_plan_mode, record_plan
from engine.dispatcher import Dispatcher
from tools.models import ToolResult
from tools.task_tool import TaskTool


class _Runner:
    response = {
        "result": "delegated finding",
        "role": "research",
        "evidence": ["E-42"],
        "files_read": ["core/example.py"],
        "tool_calls": 1,
    }

    def __init__(self, **_kwargs):
        pass

    def run(self, _prompt):
        return dict(self.response)


def _graph_state() -> RuntimeState:
    state = RuntimeState("task-graph-binding")
    enter_plan_mode(state)
    record_plan(state, ["Delegate bounded research"])
    return state


def _tool_with_fake_runner(monkeypatch) -> TaskTool:
    import engine.subagent_runner as runner_module

    monkeypatch.setattr(runner_module, "SubagentRunner", _Runner)
    tool = TaskTool()
    tool._cheap_provider = lambda _model: (lambda *_args, **_kwargs: "")
    return tool


def test_task_auto_creates_and_completes_graph_node_with_evidence(monkeypatch):
    state = _graph_state()
    tool = _tool_with_fake_runner(monkeypatch)

    result = tool.execute(
        prompt="inspect the current configuration",
        role="research",
        _parent_state=state,
    )

    assert result.success is True
    payload = json.loads(result.stdout)
    task_id = payload["task_graph_task_id"]
    assert task_id.startswith("delegated-r1-")
    assert payload["task_graph_status"] == "completed"
    assert state.task_graph.get_task(task_id).status.value == "completed"
    assert state.task_graph.get_task(task_id).evidence_ids == ("E-42",)
    assert result.metadata["task_graph_status"] == "completed"
    assert state.plan_audit[-1]["event"] == "delegated_task_completed"


def test_task_marks_auto_node_failed_when_result_has_no_evidence(monkeypatch):
    state = _graph_state()
    tool = _tool_with_fake_runner(monkeypatch)
    _Runner.response = {
        "result": "unverified answer",
        "role": "research",
        "evidence": [],
        "files_read": [],
        "tool_calls": 0,
    }

    try:
        result = tool.execute(
            prompt="inspect without tools",
            role="research",
            _parent_state=state,
        )
    finally:
        _Runner.response = {
            "result": "delegated finding",
            "role": "research",
            "evidence": ["E-42"],
            "files_read": ["core/example.py"],
            "tool_calls": 1,
        }

    task_id = result.metadata["task_graph_task_id"]
    assert result.success is False
    assert result.status == "evidence_missing"
    assert state.task_graph.get_task(task_id).status.value == "failed"
    assert state.plan_audit[-1]["event"] == "delegated_task_failed"


def test_task_refuses_existing_node_when_role_does_not_match(monkeypatch):
    state = _graph_state()
    state.task_graph.add_task("review-node", "review findings", role="review")
    tool = _tool_with_fake_runner(monkeypatch)

    result = tool.execute(
        prompt="attempt role confusion",
        role="research",
        task_id="review-node",
        _parent_state=state,
    )

    assert result.success is False
    assert result.status == "policy_denied"
    assert "role mismatch" in result.stderr
    assert state.task_graph.get_task("review-node").status.value == "ready"


def test_dispatcher_injects_parent_state_without_exposing_it_to_tool_schema():
    captured = {}

    class _Task:
        name = "task"

        def execute(self, **kwargs):
            captured.update(kwargs)
            return ToolResult(success=True, stdout="ok", status="success")

    class _Registry:
        def __contains__(self, name):
            return name == "task"

        def get_tool(self, name):
            assert name == "task"
            return _Task()

    state = RuntimeState("dispatcher-parent-state")
    dispatcher = Dispatcher(state, tool_registry=_Registry(), event_bus=SimpleNamespace(emit=lambda *_args, **_kwargs: None))

    result = dispatcher.dispatch("task", {"prompt": "inspect", "role": "research"})

    assert result.success is True
    assert captured["_parent_state"] is state
    assert captured["prompt"] == "inspect"
