"""tests/test_phase_fallback_restrictions.py — Verify emergency fallback restrictions."""

import pytest
from engine.loop import ExecutionLoop
from engine.state import RuntimeState


def test_fallback_mode_activates_after_two_failures():
    """After 2 provider failures, fallback mode activates"""
    loop = ExecutionLoop(state=RuntimeState(session_id="test_fb"))
    assert not loop.state.is_fallback_mode_active

    loop._note_provider_failure("timeout")
    assert not loop.state.is_fallback_mode_active

    loop._note_provider_failure("connection refused")
    assert loop.state.is_fallback_mode_active is True


def test_fallback_mode_filters_tools():
    """Only final_answer, search_memory, todo_write available in fallback"""
    loop = ExecutionLoop(state=RuntimeState(session_id="test_fb"))
    loop.state.is_fallback_mode_active = True
    available = loop.get_available_tools()
    assert set(available.keys()) == {"final_answer", "search_memory", "todo_write"}
    assert "execute_shell" not in available
    assert "browser_action" not in available


def test_fallback_mode_restores_on_success():
    """Successful response resets fallback mode"""
    loop = ExecutionLoop(state=RuntimeState(session_id="test_fb"))
    loop.state.is_fallback_mode_active = True
    loop._provider_fail_streak = 2
    loop.state.provider_fail_streak = 2
    loop._note_provider_success()
    assert loop.state.is_fallback_mode_active is False
    assert loop._provider_fail_streak == 0
    assert loop.state.provider_fail_streak == 0


def test_fallback_injects_restriction_prompt():
    """Fallback restriction block injected into system prompt"""
    loop = ExecutionLoop(state=RuntimeState(session_id="test_fb"))
    loop.state.is_fallback_mode_active = True
    messages = [{"role": "system", "content": "System anchor"}]
    res = loop._inject_runtime_context(messages)
    assert "RESTRICTED SAFE MODE ACTIVE" in res[0]["content"]


def test_no_fallback_prompt_when_normal():
    """No restriction block in normal mode"""
    loop = ExecutionLoop(state=RuntimeState(session_id="test_fb"))
    loop.state.is_fallback_mode_active = False
    messages = [{"role": "system", "content": "System anchor"}]
    res = loop._inject_runtime_context(messages)
    assert "RESTRICTED SAFE MODE ACTIVE" not in res[0]["content"]
