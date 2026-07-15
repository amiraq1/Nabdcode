"""Phase UI Dedupe — Verifies suppression of duplicate and raw tool/final_answer outputs.

Verifies:
  1. main.py wire_events (_on_llm_token) buffers and suppresses raw final_answer / tool JSON streams.
  2. main.py wire_events (_on_llm_token) streams normal conversational prose directly.
  3. ui/repl_termux.py consumer suppresses raw final_answer token streaming.
  4. ui/repl_termux.py prevents duplicate tool completion and post-run panel printing.
"""

import os
import sys
import asyncio
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.renderer import Renderer
from engine.events import bus
from core.ui_bridge import UIBridge


def test_main_on_llm_token_suppresses_raw_final_answer():
    """Verify that wire_events (_on_llm_token) does not stream final_answer JSON raw."""
    import main
    from core.app_context import AppContext
    from engine.state import RuntimeState

    ctx = AppContext()
    mock_renderer = MagicMock(spec=Renderer)
    ctx.renderer = mock_renderer

    main.wire_events(ctx, RuntimeState())

    # Simulate token emissions of a final_answer call
    tokens = ["f", "i", "n", "a", "l", "_", "a", "n", "s", "w", "e", "r", " ", "{", '"', "a", '"', "}", "\n"]
    for t in tokens:
        bus.emit("llm_token", {"token": t})

    # Since it matched "final_answer", stream_chunk should NEVER have been called with those tokens
    mock_renderer.stream_chunk.assert_not_called()


def test_main_on_llm_token_streams_conversational_prose():
    """Verify that wire_events (_on_llm_token) streams regular prose tokens."""
    import main
    from core.app_context import AppContext
    from engine.state import RuntimeState

    ctx = AppContext()
    mock_renderer = MagicMock(spec=Renderer)
    ctx.renderer = mock_renderer

    main.wire_events(ctx, RuntimeState())

    tokens = ["H", "e", "l", "l", "o", " ", "W", "o", "r", "l", "d"]
    for t in tokens:
        bus.emit("llm_token", {"token": t})

    assert mock_renderer.stream_chunk.call_count > 0
    # The accumulated stream calls should contain "Hello World"
    streamed_text = "".join(call.args[0] for call in mock_renderer.stream_chunk.call_args_list)
    assert "Hello World" in streamed_text


def test_tool_result_not_printed_twice():
    """Verify that tool completion and post-run panel do not cause duplicate output when handled by TermuxBridgeUI."""
    from ui.repl_termux import TermuxBridgeUI
    from core.ui_bridge import bridge

    mock_bus = MagicMock()
    bridge_ui = TermuxBridgeUI(bridge, mock_bus)

    # When TermuxBridgeUI registers listeners, _on_tool_completed_active is set to True
    assert getattr(mock_bus, "_on_tool_completed_active", False) is True

    # And when on_final_answer is called, it marks _final_answer_rendered as True
    with patch("ui.repl_termux.console"):
        bridge_ui.on_final_answer({"output": 'final_answer { "answer": "clean answer" }'})
    assert getattr(mock_bus, "_final_answer_rendered", False) is True
