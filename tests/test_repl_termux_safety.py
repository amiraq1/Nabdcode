import pytest
from unittest.mock import MagicMock
from main import _extract_final_answer_text, wire_events
from core.utils import safe_strip
from core.kernel.events import EventBus


def test_extract_final_answer_text_with_exception():
    """Verify _extract_final_answer_text does not crash with AttributeError when passed an Exception."""
    exc = Exception("Simulated VerifyError")
    result = _extract_final_answer_text(exc)
    assert result == str(exc)


def test_on_loop_completed_with_exception():
    """Verify _on_loop_completed in wire_events does not crash when output is an Exception object."""
    mock_ctx = MagicMock()
    rendered_lines = []
    mock_ctx.renderer.agent_text = lambda text: rendered_lines.append(text)
    mock_ctx.renderer.think_end = lambda: None
    mock_ctx.renderer.flush = lambda: None
    mock_ctx.renderer.error_badge = lambda badge, msg: rendered_lines.append(f"{badge}: {msg}")

    # Wire events registers _on_loop_completed on the global bus
    wire_events(mock_ctx)
    from core.kernel.events import bus

    try:
        bus.emit("loop_completed", {"output": Exception("Simulated VerifyError")})
        passed = True
    except AttributeError:
        passed = False

    assert passed, "CRITICAL: _on_loop_completed crashed with AttributeError when receiving an Exception object!"
    assert any("Simulated VerifyError" in str(line) for line in rendered_lines)


def test_repl_safe_strip_behavior():
    """Verify safe_strip handles edge cases safely across UI event payloads."""
    assert safe_strip(Exception("Tool error")) == "Tool error"
    assert safe_strip(None) == ""
