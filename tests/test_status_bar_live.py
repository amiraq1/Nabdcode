import pytest
from ui.widgets.status_bar import AgentStatusBar

def test_status_bar_no_fabrication():
    """Test that the status bar preserves step without fabricating max or phase."""
    bar = AgentStatusBar()
    
    # Send tool start with step
    bar._on_tool_start({"step": 3})
    
    assert bar._step == 3
    assert bar._phase_states["Running Tools"] == "active"
    
    # Build renderable and check text
    from rich.console import Console
    console = Console(width=80, force_terminal=False, highlight=False)
    with console.capture() as cap:
        console.print(bar._build_renderable())
    text = cap.get()
    
    assert "Step 3" in text
    assert "/max" not in text
    assert "PLAN" not in text
    assert "BUDGET" not in text
    
    # Send llm start without step
    bar._on_llm_start({})
    
    # Step should remain 3
    assert bar._step == 3
    assert bar._phase_states["Thinking"] == "active"
    
    with console.capture() as cap:
        console.print(bar._build_renderable())
    text = cap.get()
    assert "Step 3" in text
