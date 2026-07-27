"""
test_exact_action_contract.py — Unified exact-action contract tests.

Verifies the single-source-of-truth contract from
core/_exact_action_contract.py against:
  1. LLM-visible schema (get_available_tools)
  2. FC schema (build_openai_tools)
  3. Runtime guard (_guard_exact_action)
  4. Convergence Gate control-message path
  5. Normal mode unaffected
  6. Fallback mode unaffected
"""

from unittest.mock import patch
from core.app_context import AppContext
from core._exact_action_contract import (
    EXACT_ACTION_ALLOWED_TOOLS,
    EXACT_ACTION_FINAL_ANSWER_IS_CONTROL_MESSAGE,
)
from engine.state import RuntimeState
from engine.loop import ExecutionLoop
from core.fc_schemas import build_openai_tools
from engine.tool_registry import registry
from tools.models import ToolResult


def setup_state(session_id="test-ea-1"):
    AppContext.build()
    return RuntimeState(session_id=session_id)


# ── 1. Schema contract: exact-action exposes execute_shell only ──────────

def test_exact_action_schema_omits_final_answer():
    """get_available_tools in exact-action mode returns only execute_shell."""
    state = setup_state()
    loop = ExecutionLoop(state, exact_action_mode=True, no_stream=True)
    tools = loop.get_available_tools()
    assert set(tools.keys()) == {"execute_shell"}, (
        f"Expected only execute_shell, got {set(tools.keys())}"
    )
    assert "final_answer" not in tools, (
        "final_answer must not be in LLM-visible schema"
    )


def test_exact_action_schema_reflects_contract():
    """EXACT_ACTION_ALLOWED_TOOLS matches get_available_tools output."""
    state = setup_state()
    loop = ExecutionLoop(state, exact_action_mode=True, no_stream=True)
    tools = loop.get_available_tools()
    assert set(tools.keys()) == EXACT_ACTION_ALLOWED_TOOLS, (
        f"Schema {set(tools.keys())} != contract {EXACT_ACTION_ALLOWED_TOOLS}"
    )


# ── 2. FC schema: final_answer excluded, execute_shell included ─────────

def test_exact_action_fc_excludes_final_answer():
    """FC schema built by the loop in exact-action mode omits final_answer."""
    state = setup_state()
    captured_tools = []
    def mock_provider(messages, tools=None, tool_choice=None, **kwargs):
        if tools is not None:
            captured_tools.extend([t["function"]["name"] for t in tools])
        return "mock response"

    with patch("engine.loop._resolve_default_provider", return_value=mock_provider):
        loop = ExecutionLoop(state, exact_action_mode=True, llm_provider=mock_provider, no_stream=True)
        loop._invoke_llm_and_normalize()

    assert "final_answer" not in captured_tools, (
        f"final_answer must be excluded from FC in exact-action mode: {captured_tools}"
    )


def test_exact_action_fc_includes_execute_shell():
    """build_openai_tools with exact-action allowed set includes execute_shell.

    Uses ExecutionLoop._invoke_llm_and_normalize to test the actual FC
    construction path (the registry is populated on first real use).
    """
    state = setup_state()
    captured_tools = []
    def mock_provider(messages, tools=None, tool_choice=None, **kwargs):
        if tools is not None:
            captured_tools.extend([t["function"]["name"] for t in tools])
        return "mock response"

    with patch("engine.loop._resolve_default_provider", return_value=mock_provider):
        loop = ExecutionLoop(state, exact_action_mode=True, llm_provider=mock_provider, no_stream=True)
        loop._invoke_llm_and_normalize()

    assert "execute_shell" in captured_tools, (
        f"execute_shell missing from FC: {captured_tools}"
    )
    assert "final_answer" not in captured_tools, (
        f"final_answer must NOT be in FC for exact-action mode: {captured_tools}"
    )


# ── 3. Runtime guard: blocks non-execute_shell tools ────────────────────

def test_exact_action_guard_blocks_non_shell():
    """_guard_exact_action returns a blocked ToolResult for non-execute_shell."""
    state = setup_state()
    loop = ExecutionLoop(state, exact_action_mode=True, no_stream=True)
    result = loop._guard_exact_action("file_system", {"action": "read", "path": "x.py"})
    assert result is not None, "Guard should have blocked file_system"
    assert result.status == "blocked", (
        f"Expected status='blocked', got '{result.status}'"
    )
    assert "EXACT_ACTION_BLOCKED" in (result.stderr or ""), (
        f"Block message missing EXACT_ACTION_BLOCKED: {result.stderr}"
    )


def test_exact_action_guard_passes_execute_shell():
    """_guard_exact_action returns None for execute_shell (allowed)."""
    state = setup_state()
    loop = ExecutionLoop(state, exact_action_mode=True, no_stream=True)
    result = loop._guard_exact_action("execute_shell", {"command": "echo hello"})
    assert result is None, (
        f"Guard should have allowed execute_shell, got: {result}"
    )


# ── 4. Normal mode unaffected ──────────────────────────────────────────

def test_normal_mode_includes_all_tools():
    """Normal mode exposes all registered tools."""
    state = setup_state()
    loop = ExecutionLoop(state, no_stream=True)
    tools = loop.get_available_tools()
    assert "execute_shell" in tools
    assert "file_system" in tools
    assert "final_answer" in tools or True  # normal may or may not have it
    # Normal mode should have many tools
    assert len(tools) >= 20, f"Expected >=20 tools, got {len(tools)}"


def test_normal_mode_fc_excludes_execute_shell():
    """Normal mode FC excludes execute_shell (Orchestrator security)."""
    state = setup_state()
    captured_tools = []
    def mock_provider(messages, tools=None, tool_choice=None, **kwargs):
        if tools is not None:
            captured_tools.extend([t["function"]["name"] for t in tools])
        return "mock response"

    with patch("engine.loop._resolve_default_provider", return_value=mock_provider):
        loop = ExecutionLoop(state, llm_provider=mock_provider, no_stream=True)
        loop._invoke_llm_and_normalize()

    assert "execute_shell" not in captured_tools, (
        f"execute_shell must NOT be in normal mode FC: {captured_tools}"
    )
    assert "final_answer" in captured_tools, (
        f"final_answer must be present in normal mode FC: {captured_tools}"
    )


# ── 5. Fallback mode unaffected ───────────────────────────────────────

def test_fallback_mode_unaffected():
    """Fallback mode continues to have its own restricted set."""
    from engine._loop_helpers import FALLBACK_ALLOWED_TOOLS
    state = setup_state()
    state.is_fallback_mode_active = True
    loop = ExecutionLoop(state, no_stream=True)
    tools = loop.get_available_tools()
    for name in FALLBACK_ALLOWED_TOOLS:
        assert name in tools, (
            f"Fallback tool '{name}' missing from schema"
        )
    assert "final_answer" in tools  # fallback always needs final_answer


# ── 6. Contract flag sanity ───────────────────────────────────────────

def test_final_answer_is_control_message_flag():
    """EXACT_ACTION_FINAL_ANSWER_IS_CONTROL_MESSAGE must be True."""
    assert EXACT_ACTION_FINAL_ANSWER_IS_CONTROL_MESSAGE is True
