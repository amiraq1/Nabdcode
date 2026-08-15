"""Regression tests for capability-restricted delegated tasks."""

from __future__ import annotations

from typing import Any

import pytest

from engine.subagent_policy import RestrictedToolRegistry
from tools.file_system import FileSystemTool
from tools.models import ToolResult


class _Registry:
    def __init__(self, tools: dict[str, Any]) -> None:
        self._tools = tools

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def get_tool(self, name: str) -> Any:
        return self._tools[name]


class _ReadTool:
    description = "test read tool"

    def __init__(self, name: str = "search_memory") -> None:
        self.name = name

    def __call__(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, stdout="ok", returncode=0)

    def get_schema(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}


def _registry_with_file_tool(tmp_path) -> _Registry:
    return _Registry(
        {
            "file_system": FileSystemTool(workspace=tmp_path),
            "search_memory": _ReadTool("search_memory"),
            "web_search": _ReadTool("web_search"),
            "code_intelligence": _ReadTool("code_intelligence"),
            "execute_shell": _ReadTool("execute_shell"),
            "task": _ReadTool("task"),
        }
    )


def test_restricted_registry_hides_execution_and_nested_delegation(tmp_path):
    registry = RestrictedToolRegistry(_registry_with_file_tool(tmp_path))

    assert "file_system" in registry
    assert "search_memory" in registry
    assert "execute_shell" not in registry
    assert "task" not in registry
    assert {schema["name"] for schema in registry.get_all_schemas()} == {
        "file_system",
        "search_memory",
        "web_search",
        "code_intelligence",
    }


def test_restricted_file_tool_allows_read_and_denies_write(tmp_path):
    (tmp_path / "notes.txt").write_text("read-only evidence", encoding="utf-8")
    registry = RestrictedToolRegistry(_registry_with_file_tool(tmp_path))
    file_tool = registry.get_tool("file_system")

    read = file_tool(action="read", path="notes.txt")
    blocked = file_tool(action="write", path="new.txt", content="must not exist")

    assert read.success is True
    assert "read-only evidence" in read.stdout
    assert blocked.success is False
    assert blocked.status == "policy_denied"
    assert not (tmp_path / "new.txt").exists()


def test_subagent_runner_injects_restricted_registry_and_step_budget(tmp_path, monkeypatch):
    import engine.subagent_runner as runner_module

    captured: dict[str, Any] = {}

    class _FakeLoop:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self._last_response = "delegated result"

        def run(self, prompt: str) -> None:
            captured["prompt"] = prompt

    monkeypatch.setattr(runner_module, "ExecutionLoop", _FakeLoop)
    source_registry = _registry_with_file_tool(tmp_path)
    runner = runner_module.SubagentRunner(
        router=lambda *_args, **_kwargs: "",
        max_rounds=3,
        timeout=5,
        tool_registry=source_registry,
    )

    result = runner.run("inspect the repository")
    policy_registry = captured["tool_registry"]

    assert captured["state"].max_steps == 3
    assert "execute_shell" not in policy_registry
    assert "task" not in policy_registry
    assert captured["dispatcher"].registry is policy_registry
    assert result["result"] == "delegated result"


def test_roles_are_explicit_and_fail_closed(tmp_path):
    from engine.subagent_policy import ROLE_TOOL_ALLOWLISTS, RestrictedToolRegistry

    source = _registry_with_file_tool(tmp_path)
    research = RestrictedToolRegistry(source, role="research")
    review = RestrictedToolRegistry(source, role="review")
    implement = RestrictedToolRegistry(source, role="implement")

    assert set(research._tools) <= ROLE_TOOL_ALLOWLISTS["research"]
    assert set(review._tools) <= ROLE_TOOL_ALLOWLISTS["review"]
    assert "execute_shell" not in research
    assert "execute_shell" not in review
    assert "execute_shell" in implement
    assert "task" not in implement
    assert research.role == "research"
    assert review.role == "review"
    assert implement.role == "implement"

    with pytest.raises(ValueError, match="Unknown sub-agent role"):
        RestrictedToolRegistry(source, role="admin")


def test_implement_role_uses_real_file_tool_but_never_nested_task(tmp_path):
    registry = RestrictedToolRegistry(_registry_with_file_tool(tmp_path), role="implement")
    assert registry.get_tool("file_system").__class__.__name__ == "FileSystemTool"
    assert "task" not in registry


def test_runner_passes_role_to_policy_registry(tmp_path, monkeypatch):
    import engine.subagent_runner as runner_module

    captured = {}

    class _FakeLoop:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self._last_response = "reviewed"

        def run(self, prompt):
            captured["prompt"] = prompt

    monkeypatch.setattr(runner_module, "ExecutionLoop", _FakeLoop)
    runner = runner_module.SubagentRunner(
        router=lambda *_args, **_kwargs: "",
        max_rounds=2,
        timeout=5,
        tool_registry=_registry_with_file_tool(tmp_path),
        role="review",
    )
    result = runner.run("review the patch")

    assert result["role"] == "review"
    assert captured["tool_registry"].role == "review"
    assert "execute_shell" not in captured["tool_registry"]


def test_task_input_defaults_to_research_and_exposes_role():
    from tools.task_tool import TaskInput

    task = TaskInput(prompt="inspect")
    assert task.role == "research"
    assert TaskInput.model_json_schema()["properties"]["role"]["default"] == "research"
