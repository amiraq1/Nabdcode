"""Tests for Phase 1 Single Renderer Architecture & EventBus-UIBridge relay.

Verifies:
  1. Single-direction flow (plan 1.1): EventBus -> UIBridge works; UIBridge
     does NOT relay back into EventBus (no echo / infinite loop). The renderer
     is a reader only — it never writes back to the bus.
  2. Single Renderer ownership: wire_events yields when TerminalVisualizer is
     active (_on_tool_completed_active == True).
  3. Single Renderer ownership: wire_events renders via Renderer when
     TerminalVisualizer is not active.
  4. Tool emission deduplication: BaseTool.forward suppresses bridge emissions
     when inside Dispatcher.dispatch.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.kernel.events import bus
from core.ui_bridge import UIBridge, get_bridge, set_bridge
from engine.renderer import Renderer
from engine.dispatcher import _dispatch_ctx, is_dispatching


def test_bus_to_bridge_relay_is_one_way():
    """Verify EventBus -> UIBridge works, but UIBridge does NOT relay back into
    EventBus (plan 1.1: single source of truth, one-way flow, no echo)."""
    test_bridge = UIBridge()
    set_bridge(test_bridge)
    try:
        events_seen_on_bus = []
        events_seen_on_bridge = []

        def bus_cb(payload):
            events_seen_on_bus.append(payload)

        class ObsBridge(UIBridge):
            def on_action_triggered(self, action_type, target, meta=""):
                events_seen_on_bridge.append((action_type, target, meta))
            def on_status_changed(self, status_text):
                events_seen_on_bridge.append(("status", status_text))

        obs_bridge = ObsBridge()
        set_bridge(obs_bridge)

        unsub = bus.subscribe("custom_test_event", bus_cb)
        try:
            # 1. Emit on bus -> should arrive at bridge (forward direction).
            bus.emit("status_update", {"message": "System check ok"})
            assert any(item[0] == "status" and item[1] == "System check ok" for item in events_seen_on_bridge)

            # 2. Emit on bridge -> must NOT arrive back on the bus (no echo).
            # The renderer is a reader only; it never writes back to EventBus.
            before = len(events_seen_on_bus)
            obs_bridge.emit("custom_test_event", data="hello world")
            assert len(events_seen_on_bus) == before, "bridge must NOT relay back into EventBus"
            # Sanity: the bridge still fans out to its own observers.
            assert any(isinstance(item, tuple) and item[0] == "custom_test_event" for item in events_seen_on_bridge)
        finally:
            unsub()
    finally:
        set_bridge(None)


def test_wire_events_yields_when_visualizer_active():
    """Verify wire_events (_on_tool_started, _on_tool_completed, _on_llm_token) yields to TerminalVisualizer when active."""
    import main
    from core.app_context import AppContext

    ctx = AppContext.build()
    mock_renderer = MagicMock(spec=Renderer)
    ctx.renderer = mock_renderer
    main.wire_events(ctx)

    # Simulate TerminalVisualizer active
    bus._on_tool_completed_active = True
    try:
        bus.emit("tool_started", {"tool": "shell", "args": {"command": "ls"}})
        bus.emit("tool_completed", {"tool": "shell", "result": MagicMock(success=True, stdout="output")})
        bus.emit("llm_token", {"token": "hello"})

        mock_renderer.tool_start.assert_not_called()
        mock_renderer.tool_end.assert_not_called()
        mock_renderer.stream_chunk.assert_not_called()
    finally:
        bus._on_tool_completed_active = False


def test_wire_events_renders_when_visualizer_inactive():
    """Verify wire_events (_on_tool_started, _on_tool_completed, _on_llm_token) renders via Renderer when no visualizer active."""
    import main
    from core.app_context import AppContext

    ctx = AppContext.build()
    mock_renderer = MagicMock(spec=Renderer)
    ctx.renderer = mock_renderer
    main.wire_events(ctx)

    bus._on_tool_completed_active = False
    bus.emit("tool_started", {"tool": "shell", "args": {"command": "ls"}})
    bus.emit("tool_completed", {"tool": "shell", "result": MagicMock(success=True, stdout="output")})
    bus.emit("llm_token", {"token": "hello"})

    mock_renderer.tool_start.assert_called_once_with("shell", {"command": "ls"})
    mock_renderer.tool_end.assert_called_once()
    mock_renderer.stream_chunk.assert_called_once_with("hello")


def test_basetool_forward_suppresses_bridge_emits_during_dispatch():
    """Verify BaseTool.forward does not double-emit tool start/end when running inside Dispatcher.dispatch."""
    from tools.base import BaseTool
    from tools.models import ToolResult

    class DummyTool(BaseTool):
        name = "dummy_test_tool"
        description = "dummy"
        def execute(self, args):
            return self.execute_with_args(args)
        def execute_with_args(self, args):
            return ToolResult(success=True, stdout="dummy output")

    tool = DummyTool()
    mock_bridge = MagicMock()
    with patch("core.ui_bridge.get_bridge", return_value=mock_bridge):
        # 1. Outside dispatch: should emit
        _dispatch_ctx.active = False
        tool.forward({"args": ["hi"]})
        assert mock_bridge.emit_tool_start_sync.call_count == 1
        assert mock_bridge.emit_tool_end_sync.call_count == 1

        mock_bridge.reset_mock()

        # 2. Inside dispatch: should suppress
        _dispatch_ctx.active = True
        try:
            tool.forward({"args": ["hi"]})
            mock_bridge.emit_tool_start_sync.assert_not_called()
            mock_bridge.emit_tool_end_sync.assert_not_called()
        finally:
            _dispatch_ctx.active = False
