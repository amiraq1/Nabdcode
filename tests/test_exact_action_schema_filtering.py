import pytest
from unittest.mock import patch
from core.app_context import AppContext
from core._exact_action_contract import EXACT_ACTION_ALLOWED_TOOLS
from engine.state import RuntimeState
from engine.loop import ExecutionLoop
from core.fc_schemas import build_openai_tools
from engine.tool_registry import registry

@pytest.fixture(autouse=True)
def setup_context():
    AppContext.build()

def test_exact_action_mode_fc_schema_filtering():
    """Exact-action mode exposes only execute_shell (no final_answer as LLM tool).

    Under the unified contract, final_answer is excluded from the FC schema
    in exact-action mode — it is only injected as a system-level control
    message by the Convergence Gate.
    """
    state = RuntimeState(session_id="test-1")
    captured_tools = []
    def mock_provider(messages, tools=None, tool_choice=None, **kwargs):
        if tools is not None:
            captured_tools.extend([t["function"]["name"] for t in tools])
        return "mock response"
        
    with patch("engine.loop._resolve_default_provider", return_value=mock_provider):
        loop = ExecutionLoop(state, exact_action_mode=True, llm_provider=mock_provider, no_stream=True)
        loop._invoke_llm_and_normalize()
    
    assert captured_tools == ["execute_shell"], (
        f"Expected ['execute_shell'], got {captured_tools}. "
        "final_answer must NOT be exposed as an LLM tool in exact-action mode."
    )
    assert "final_answer" not in captured_tools, (
        "final_answer must NOT be in FC schema for exact-action mode"
    )

def test_normal_mode_fc_schema_filtering():
    state = RuntimeState(session_id="test-2")
    captured_tools = []
    def mock_provider(messages, tools=None, tool_choice=None, **kwargs):
        if tools is not None:
            captured_tools.extend([t["function"]["name"] for t in tools])
        return "mock response"
        
    with patch("engine.loop._resolve_default_provider", return_value=mock_provider):
        loop = ExecutionLoop(state, llm_provider=mock_provider, no_stream=True)
        loop._invoke_llm_and_normalize()
    
    assert len(captured_tools) == 25, f"Expected 25 tools, got {len(captured_tools)}"
    assert "execute_shell" not in captured_tools
    assert "final_answer" in captured_tools

def test_fallback_mode_fc_schema_filtering():
    state = RuntimeState(session_id="test-3")
    state.is_fallback_mode_active = True
    captured_tools = []
    def mock_provider(messages, tools=None, tool_choice=None, **kwargs):
        if tools is not None:
            captured_tools.extend([t["function"]["name"] for t in tools])
        return "mock response"
        
    with patch("engine.loop._resolve_default_provider", return_value=mock_provider):
        loop = ExecutionLoop(state, llm_provider=mock_provider, no_stream=True)
        loop._invoke_llm_and_normalize()
    
    assert len(captured_tools) == 3, f"Expected 3 tools, got {len(captured_tools)}"
    assert set(captured_tools) == {"final_answer", "search_memory", "todo_write"}
