#!/usr/bin/env python3
"""
tests/test_exe03_session_event_isolation.py — Session & Event Bus Isolation Tests
================================================================================
Validates EXE-03 requirements:
  1. Dependency Injection: ToolRegistry and EventBus can be injected locally.
  2. Session Isolation: Tools registered in Session A do not leak to Session B.
  3. Event Isolation: Events emitted on Bus A are not received by Bus B subscribers.
  4. Event Payloads include session_id invariant.
  5. Dispatcher operates cleanly on injected context without global state coupling.
"""

from __future__ import annotations

import unittest

from core.kernel.events import EventBus
from engine.dispatcher import Dispatcher
from engine.loop import ExecutionLoop
from engine.state import RuntimeState
from engine.tool_registry import ToolRegistry
from tools.base import BaseTool
from tools.models import ToolResult


class _CustomSessionTool(BaseTool):
    """Custom tool for session-specific registration."""

    def __init__(self, name: str, output: str):
        super().__init__()
        self.name = name
        self.description = f"Custom tool {name}"
        self.output = output

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, stdout=self.output, returncode=0, status="success")


class TestSessionEventIsolation(unittest.TestCase):
    """Test suite for concurrent session and event isolation."""

    def test_tool_registry_session_isolation(self):
        """A tool registered in Session A must not appear in Session B."""
        registry_a = ToolRegistry()
        registry_b = ToolRegistry()

        tool_a = _CustomSessionTool(name="session_a_tool", output="output_a")
        registry_a.register(tool_a)

        # Assert Session A has the tool
        self.assertIn("session_a_tool", registry_a)
        self.assertEqual(registry_a.get_tool("session_a_tool").output, "output_a")

        # Assert Session B does NOT have the tool
        self.assertNotIn("session_a_tool", registry_b)
        with self.assertRaises(KeyError):
            registry_b.get_tool("session_a_tool")

    def test_event_bus_session_isolation(self):
        """Events emitted on Bus A must not leak to subscribers on Bus B."""
        bus_a = EventBus()
        bus_b = EventBus()

        events_a = []
        events_b = []

        bus_a.subscribe("tool_started", lambda payload: events_a.append(payload))
        bus_b.subscribe("tool_started", lambda payload: events_b.append(payload))

        # Emit on Bus A with session_id
        bus_a.emit("tool_started", {"tool": "test_tool", "step": 1}, session_id="session_A")

        # Bus A receives the event with session_id attached
        self.assertEqual(len(events_a), 1)
        self.assertEqual(events_a[0]["session_id"], "session_A")
        self.assertEqual(events_a[0]["tool"], "test_tool")

        # Bus B receives NOTHING
        self.assertEqual(len(events_b), 0)

    def test_dispatcher_injected_session_isolation(self):
        """Two Dispatchers with separate state/registry/bus execute in complete isolation."""
        state_a = RuntimeState(session_id="session_alpha")
        registry_a = ToolRegistry()
        bus_a = EventBus()
        tool_a = _CustomSessionTool(name="isolated_tool", output="alpha_result")
        registry_a.register(tool_a)

        state_b = RuntimeState(session_id="session_beta")
        registry_b = ToolRegistry()
        bus_b = EventBus()
        tool_b = _CustomSessionTool(name="isolated_tool", output="beta_result")
        registry_b.register(tool_b)

        dispatcher_a = Dispatcher(state_a, tool_registry=registry_a, event_bus=bus_a)
        dispatcher_b = Dispatcher(state_b, tool_registry=registry_b, event_bus=bus_b)

        bus_a_events = []
        bus_b_events = []
        bus_a.subscribe("tool_completed", lambda p: bus_a_events.append(p))
        bus_b.subscribe("tool_completed", lambda p: bus_b_events.append(p))

        # Execute on Dispatcher A
        res_a = dispatcher_a.dispatch("isolated_tool", {}, timeout=2.0)
        self.assertEqual(res_a.stdout, "alpha_result")
        self.assertEqual(len(bus_a_events), 1)
        self.assertEqual(bus_a_events[0]["session_id"], "session_alpha")
        self.assertEqual(len(bus_b_events), 0)

        # Execute on Dispatcher B
        res_b = dispatcher_b.dispatch("isolated_tool", {}, timeout=2.0)
        self.assertEqual(res_b.stdout, "beta_result")
        self.assertEqual(len(bus_b_events), 1)
        self.assertEqual(bus_b_events[0]["session_id"], "session_beta")
        self.assertEqual(len(bus_a_events), 1)

    def test_execution_loop_accepts_injected_registry_and_bus(self):
        """ExecutionLoop correctly accepts and propagates injected tool_registry and event_bus."""
        state = RuntimeState(session_id="session_loop_test")
        reg = ToolRegistry()
        eb = EventBus()

        loop = ExecutionLoop(
            state,
            tool_registry=reg,
            event_bus=eb,
            no_stream=True,
        )

        self.assertIs(loop.tool_registry, reg)
        self.assertIs(loop.event_bus, eb)
        self.assertIs(loop.dispatcher.registry, reg)
        self.assertIs(loop.dispatcher.bus, eb)


if __name__ == "__main__":
    unittest.main()
