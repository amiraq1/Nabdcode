import pytest
from ui.widgets.status_bar import AgentStatusBar
from tests.support.render import render_to_text


def test_status_bar_no_fabrication():
    """Test that the status bar preserves step without fabricating max or phase."""
    bar = AgentStatusBar()

    # Send tool start with step
    bar._on_tool_start({"step": 3})

    assert bar._step == 3
    assert bar._phase_states["Running Tools"] == "active"

    # Build renderable and check text
    text = render_to_text(bar._build_renderable(), width=80, height=25)

    assert "Step 3" in text
    assert "/max" not in text
    assert "PLAN" not in text
    assert "BUDGET" not in text

    # Send llm start without step
    bar._on_llm_start({})

    # Step should remain 3
    assert bar._step == 3
    assert bar._phase_states["Thinking"] == "active"

    text = render_to_text(bar._build_renderable(), width=80, height=25)
    assert "Step 3" in text
