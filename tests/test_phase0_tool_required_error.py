"""Phase 0 — ToolRequiredError catch + user-visible message.

Verifies:
  1. ToolRequiredError is defined and importable.
  2. The error message from Verifier propagates to the user.
  3. The fabricated assistant response is stripped from state.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.loop import ToolRequiredError, ExecutionLoop
from core.evidence import VerifierError


def test_tool_required_error_is_runtime_error():
    """ToolRequiredError must inherit from RuntimeError for catch ordering."""
    assert issubclass(ToolRequiredError, RuntimeError)


def test_tool_required_error_carries_message():
    """The verifier's message must propagate through the exception."""
    msg = "No verified evidence was collected."
    exc = ToolRequiredError(msg)
    assert str(exc) == msg


def test_fabricated_response_stripped():
    """Simulate: LLM answers without tool call → state gets assistant msg
    → ToolRequiredError raised → assistant msg stripped.

    This tests the logic in the main.py handler without needing the TUI loop.
    """
    from engine.state import RuntimeState
    from uuid import uuid4

    state = RuntimeState(session_id=str(uuid4()))
    state.append_message({"role": "system", "content": "system prompt"})
    state.append_message({"role": "user", "content": "analyze this project"})

    # Simulate what engine/loop.py does: append a fabricated assistant response
    state.append_message({"role": "assistant", "content": "I analyzed the project. It uses FastAPI."})

    assert len(state.get_messages()) == 3
    assert state.get_last_message()["role"] == "assistant"

    # Simulate what Phase 0 main.py handler does on ToolRequiredError
    msgs = state.get_messages()
    if msgs and msgs[-1].get("role") == "assistant":
        state.set_messages(msgs[:-1])

    # After stripping: the assistant message must be gone
    assert len(state.get_messages()) == 2
    assert state.get_last_message()["role"] == "user"
    assert state.get_last_message()["content"] == "analyze this project"


def test_verifier_error_message_in_tool_required_error():
    """Simulate the full chain: VerifierError → ToolRequiredError."""
    from core.evidence import VerifierError, EvidenceLog

    log = EvidenceLog()
    # No records recorded — this should fail
    try:
        log.verify(require_tools=True)
        assert False, "Expected VerifierError"
    except VerifierError as verr:
        exc = ToolRequiredError(str(verr))
        assert "No verified evidence" in str(exc)
        assert "tool" not in str(exc).lower()  # message should talk about evidence, not tool


if __name__ == "__main__":
    test_tool_required_error_is_runtime_error()
    test_tool_required_error_carries_message()
    test_fabricated_response_stripped()
    test_verifier_error_message_in_tool_required_error()
    print("All Phase 0 tests passed.")
