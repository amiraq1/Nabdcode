"""Adversarial regressions for Task Graph, role, and Plan/Apply boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.kernel.state import RuntimeState
from core.plan_apply import record_plan, start_task
from core.task_graph import TaskGraphError, TaskStatus
from engine.subagent_policy import RestrictedToolRegistry
from tools.models import ToolResult


class _Registry:
    def __init__(self) -> None:
        self._tools = {
            name: _Tool(name)
            for name in (
                "file_system",
                "execute_shell",
                "todo_write",
                "search_memory",
                "code_intelligence",
                "task",
            )
        }

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def get_tool(self, name: str):
        return self._tools[name]


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name

    def __call__(self, **_kwargs):
        return ToolResult(success=True, stdout="ok")

    def get_schema(self):
        return {"name": self.name, "description": self.description}


def test_red_team_implement_cannot_forge_apply_through_workflow_facade():
    state = RuntimeState("red-team-implement")
    record_plan(state, ["Apply guarded change"])
    state.task_graph.add_task("apply", "mutate workspace", role="implement")

    with pytest.raises(TaskGraphError, match="Plan/Apply authorization"):
        start_task(state, "apply", role="implement")

    assert state.task_graph.get_task("apply").status == TaskStatus.READY


def test_red_team_role_confusion_is_rejected_at_authority_seam():
    state = RuntimeState("red-team-role")
    record_plan(state, ["Research only"])
    state.task_graph.add_task("inspect", "read source", role="research")

    with pytest.raises(TaskGraphError, match="role mismatch"):
        start_task(state, "inspect", role="implement")

    assert state.task_graph.get_task("inspect").status == TaskStatus.READY


def test_red_team_new_revision_discards_old_graph_nodes():
    state = RuntimeState("red-team-stale")
    record_plan(state, ["Original scope"])
    state.task_graph.add_task("legacy", "old task", role="research")
    old_graph = state.task_graph

    record_plan(state, ["Revised scope"])

    with pytest.raises(TaskGraphError, match="unknown task_id"):
        start_task(state, "legacy", role="research")
    assert old_graph.get_task("legacy").status == TaskStatus.READY
    assert state.task_graph is not old_graph


def test_red_team_implement_registry_never_exposes_nested_task():
    registry = RestrictedToolRegistry(_Registry(), role="implement")

    assert "execute_shell" in registry
    assert "task" not in registry
    with pytest.raises(KeyError, match="not permitted"):
        registry.get_tool("task")
