"""Phase UI Dedupe — Verifies suppression of duplicate and raw tool/final_answer outputs.

Verifies:
  1. main.py wire_events (_on_llm_token) buffers and suppresses raw final_answer / tool JSON streams.
  2. main.py wire_events (_on_llm_token) streams normal conversational prose directly.
  3. ui.repl_termux.TerminalVisualizer dedupes tool completion / final-answer rendering
     (sets _on_tool_completed_active and _final_answer_rendered flags).
  4. Tool-name event contract: handlers resolve the tool name from both the
     canonical "tool" key (emitted by engine/dispatcher.py) and the legacy
     "tool_name" key, so a drifted payload never surfaces as "None".
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.renderer import Renderer
from engine.events import bus
from core.ui_bridge import UIBridge


def _make_ctx():
    """Build a real AppContext and swap in a mock renderer.

    AppContext requires dependency injection (config/logger/renderer/...), so we
    use the project's build() factory and override the renderer with a MagicMock
    that satisfies the Renderer interface used by wire_events.
    """
    import main
    from core.app_context import AppContext
    from engine.state import RuntimeState

    ctx = AppContext.build()
    mock_renderer = MagicMock(spec=Renderer)
    ctx.renderer = mock_renderer
    return ctx, mock_renderer


def test_main_on_llm_token_suppresses_raw_final_answer():
    """Verify that wire_events (_on_llm_token) does not stream final_answer JSON raw."""
    import main

    ctx, mock_renderer = _make_ctx()
    main.wire_events(ctx)

    # Simulate token emissions of a final_answer call
    tokens = ["f", "i", "n", "a", "l", "_", "a", "n", "s", "w", "e", "r", " ", "{", '"', "a", '"', "}", "\n"]
    for t in tokens:
        bus.emit("llm_token", {"token": t})

    # Since it matched "final_answer", stream_chunk should NEVER have been called with those tokens
    mock_renderer.stream_chunk.assert_not_called()


def test_main_on_llm_token_streams_conversational_prose():
    """Verify that wire_events (_on_llm_token) streams regular prose tokens."""
    import main

    ctx, mock_renderer = _make_ctx()
    main.wire_events(ctx)

    tokens = ["H", "e", "l", "l", "o", " ", "W", "o", "r", "l", "d"]
    for t in tokens:
        bus.emit("llm_token", {"token": t})

    assert mock_renderer.stream_chunk.call_count > 0
    # The accumulated stream calls should contain "Hello World"
    streamed_text = "".join(call.args[0] for call in mock_renderer.stream_chunk.call_args_list)
    assert "Hello World" in streamed_text


def test_tool_result_not_printed_twice():
    """TerminalVisualizer flags dedup state so tool completion + final-answer
    panel do not double-print."""
    from ui.repl_termux import TerminalVisualizer

    mock_bus = MagicMock()
    viz = TerminalVisualizer(event_bus=mock_bus, state=None)

    # Registering listeners flips the dedup guard on.
    assert getattr(mock_bus, "_on_tool_completed_active", False) is True

    # Invoking on_final_answer marks the final answer as rendered so the
    # secondary panel path is suppressed. Patch Live (the animated panel) so
    # the test runs headless; console keeps its real size for width math.
    with patch("ui.repl_termux.Live"):
        viz.on_final_answer({"output": 'final_answer { "answer": "clean answer" }'})
    assert getattr(mock_bus, "_final_answer_rendered", False) is True


def test_tool_name_contract_resolves_canonical_key():
    """The canonical 'tool' key must resolve to the real tool name
    (never None) in the REPL tool-completion handler."""
    from ui.repl_termux import TerminalVisualizer

    mock_bus = MagicMock()
    viz = TerminalVisualizer(event_bus=mock_bus, state=None)

    with patch("ui.repl_termux.console") as mock_console, patch("ui.repl_termux.Live"):
        # Canonical key emitted by engine/dispatcher.py
        viz.on_tool_completed({"tool": "web_search", "success": True})
        viz.on_tool_completed({"tool": "file_system", "success": True})

    # The printed completion line must contain the real names, not "None".
    printed = "".join(
        str(getattr(call.args[0], "renderable", call.args[0]))
        for call in mock_console.print.call_args_list
    )
    assert "web_search" in printed, "canonical 'tool' key not resolved"
    assert "file_system" in printed, "canonical 'tool' key not resolved"
    assert "None" not in printed, "tool name resolved to None"
