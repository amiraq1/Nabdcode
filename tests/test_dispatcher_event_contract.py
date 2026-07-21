"""
Regression tests verifying exact payload shape contracts for tool_started and tool_completed events.
Ensures UI/listeners (e.g. core.ui_bridge, ui.repl_termux) never break due to payload structure shifts.
"""
import pytest
from unittest.mock import MagicMock
from core.kernel.events import EventBus
from engine.dispatcher import Dispatcher
from engine.state import RuntimeState
from tools.models import ToolResult
from engine.tool_registry import ToolRegistry


class DummyTool:
    name = "dummy_tool"
    description = "A dummy tool for contract verification"

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, stdout="hello world", returncode=0, diff="+ hello")

    def __call__(self, *args, **kwargs) -> ToolResult:
        return self.execute(**kwargs)

    def get_schema(self) -> dict:
        return {"name": self.name, "description": self.description}


def test_tool_started_and_completed_payload_contract(monkeypatch):
    """Verify that Dispatcher.dispatch emits tool_started and tool_completed with exact required keys and types."""
    # Create isolated bus and registry for testing
    test_bus = EventBus()
    test_registry = ToolRegistry()
    test_registry.register("dummy_tool", DummyTool())

    # Monkeypatch global bus and registry used by Dispatcher
    monkeypatch.setattr("engine.dispatcher.bus", test_bus)
    monkeypatch.setattr("engine.dispatcher.registry", test_registry)

    started_payloads = []
    completed_payloads = []

    def on_started(data: dict):
        started_payloads.append(data)

    def on_completed(data: dict):
        completed_payloads.append(data)

    test_bus.subscribe("tool_started", on_started)
    test_bus.subscribe("tool_completed", on_completed)

    state = RuntimeState(session_id="test_contract", max_steps=10)
    state.step_count = 3
    dispatcher = Dispatcher(state)

    result = dispatcher.dispatch("dummy_tool", {"param": "val"})

    assert result.success is True
    assert len(started_payloads) == 1
    assert len(completed_payloads) == 1

    # 1. Verify exact keys and types for tool_started payload
    started = started_payloads[0]
    assert set(started.keys()) == {"tool", "args", "step"}
    assert isinstance(started["tool"], str) and started["tool"] == "dummy_tool"
    assert isinstance(started["args"], dict) and started["args"] == {"param": "val"}
    assert isinstance(started["step"], int) and started["step"] == 3

    # 2. Verify exact keys and types for tool_completed payload
    completed = completed_payloads[0]
    assert set(completed.keys()) == {"tool", "result", "success", "returncode", "diff", "step"}
    assert isinstance(completed["tool"], str) and completed["tool"] == "dummy_tool"
    assert isinstance(completed["result"], ToolResult)
    assert isinstance(completed["success"], bool) and completed["success"] is True
    assert isinstance(completed["returncode"], int) and completed["returncode"] == 0
    assert isinstance(completed["diff"], str) and completed["diff"] == "+ hello"
    assert isinstance(completed["step"], int) and completed["step"] == 3
