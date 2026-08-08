"""tests/test_on_loop_completed_spacing.py — A.3 guard for RTL/Spacing overlap."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from ui.repl_termux import TerminalVisualizer
from core.state_manager import RuntimeState
from rich.panel import Panel

def test_on_loop_completed_prints_trailing_newline():
    """
    A.3: Verify that on_loop_completed prints an explicit newline/empty line
    after the final Panel so it doesn't overlap visually with the next prompt.
    """
    state = RuntimeState(session_id="test")
    renderer = TerminalVisualizer(event_bus=MagicMock(), state=state)
    renderer.live_context = MagicMock()
    
    with patch("ui.repl_termux.console.print") as mock_print:
        # Simulate a tool completion response
        renderer.on_loop_completed({"output": "code_intelligence(action='get_definition')"})
        
        # We expect two print calls: 1 for the Panel, 1 for the empty spacing
        assert mock_print.call_count >= 2, "Expected at least 2 print calls (Panel + newline)"
        
        # The last print should be an empty print() for the newline
        args, kwargs = mock_print.call_args_list[-1]
        assert len(args) == 0, "Last print call must be empty to emit a newline"
