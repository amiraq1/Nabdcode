"""Tests for subagent delegation (task tool)."""

from __future__ import annotations

import pytest

from tools.task_tool import TaskTool, TaskInput
from tools.base import BaseModel


class TestTaskTool:
    def test_tool_definition(self):
        """Tool has correct name and a Pydantic args_schema exposing 'prompt'."""
        tool = TaskTool()
        assert tool.name == "task"
        schema = tool.args_schema
        assert issubclass(schema, BaseModel)
        assert "prompt" in schema.model_fields

    def test_task_input_schema(self):
        """TaskInput requires prompt, accepts optional model."""
        ti = TaskInput(prompt="count the py files")
        assert ti.prompt == "count the py files"
        assert ti.model is None
        # model override
        ti2 = TaskInput(prompt="x", model="google/gemini-2.5-flash")
        assert ti2.model == "google/gemini-2.5-flash"

    def test_execute_empty_prompt_rejected(self):
        """Empty prompt must fail fast without spawning a sub-loop."""
        tool = TaskTool()
        res = tool.execute(prompt="   ")
        assert res.success is False


class TestCheapestModel:
    def test_cheapest_model_returns_string(self):
        """ProviderRouter.cheapest_model() returns a non-empty string."""
        from llm_router import router

        cheap = router.cheapest_model()
        assert isinstance(cheap, str)
        assert cheap


class TestSubagentRunnerResultShape:
    def test_runner_returns_dict_with_result(self):
        """SubagentRunner.run returns a dict; on a trivial no-op it still
        returns the expected shape (error or result key present)."""
        from engine.subagent_runner import SubagentRunner

        # Use a provider that returns an empty string immediately so we don't
        # hit the network. The runner must return a dict regardless.
        def fake_provider(messages, **kwargs):
            return ""

        runner = SubagentRunner(router=fake_provider, max_rounds=5, timeout=10)
        out = runner.run("do a trivial thing")
        assert isinstance(out, dict)
        # Either a successful result container or an error container.
        assert "result" in out
