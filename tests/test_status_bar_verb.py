from ui.design.primitives.personality import style_of
from ui.design.state import UIState
from ui.widgets.status_bar import AgentStatusBar
from tests.support.render import render_to_text


def test_active_state_speaks_its_verb():
    bar = AgentStatusBar()
    bar._on_tool_start({"step": 3})
    text = render_to_text(bar._build_renderable(), width=80, height=25)

    assert style_of(UIState.RUNNING).verb in text
    assert "Step 3" in text
