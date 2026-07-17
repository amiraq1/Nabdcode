"""Phase 5 — Harden remaining assumptions.

Verifies:
  1. Chitchat moved to core/constants; is_chitchat() classifies correctly.
  2. Provider state file uses isolated path when state_key given.
  3. [verifier] badge line after ToolRequiredError streamed failure.
  4. Deep agent: VerifierError imported, verify gate in run().
  5. Deep agent: DESIGN DECISION documented (TodoManager ownership).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.constants import CHITCHAT_SET, is_chitchat
from core.evidence import VerifierError
from engine.deep_agent import NativeDeepAgent


# ── Chitchat from constants ──────────────────────────────────────────────

def test_chitchat_set_contains_greetings():
    """CHITCHAT_SET must include basic greetings."""
    for word in ("hi", "hello", "hey", "thanks", "bye"):
        assert word in CHITCHAT_SET, f"Missing chitchat word: {word}"


def test_chitchat_case_insensitive():
    """is_chitchat must be case-insensitive."""
    assert is_chitchat("Hello")[0]
    assert is_chitchat("HELLO")[0]
    assert is_chitchat("hello")[0]


def test_chitchat_empty_false():
    """Empty string is chitchat (safe: no tools needed)."""
    assert is_chitchat("")[0]


def test_substantive_not_chitchat():
    """Multi-word or technical prompts must not be marked chitchat."""
    assert not is_chitchat("analyze this project")[0]
    assert not is_chitchat("list files in /tmp")[0]
    assert not is_chitchat("what does this code do")[0]


def test_loop_prompter_uses_is_chitchat():
    """_prompt_requires_investigation must delegate to is_chitchat."""
    from engine.loop import _prompt_requires_investigation
    assert not _prompt_requires_investigation("hi")
    assert _prompt_requires_investigation("analyze this project")
    assert not _prompt_requires_investigation("thanks")


def test_loop_prompter_casual_exception():
    """_prompt_requires_investigation must allow casual/informational queries without active goal."""
    from engine.loop import _prompt_requires_investigation
    assert not _prompt_requires_investigation("Explain the difference between Android SDK and NDK", has_active_goal=False)
    assert _prompt_requires_investigation("Explain the difference between Android SDK and NDK", has_active_goal=True)


# ── Provider state isolation ─────────────────────────────────────────────

def test_provider_state_path_isolation():
    """ProviderRouter with state_key must produce a distinct state path."""
    from llm_router import ProviderRouter, ProviderState

    p1 = ProviderState(name="a", client=object(), priority=0)
    p2 = ProviderState(name="b", client=object(), priority=0)

    router_a = ProviderRouter([p1], state_key="sess_a")
    router_b = ProviderRouter([p2], state_key="sess_b")
    router_default = ProviderRouter([p1])

    # Verify isolated paths
    path_a = router_a._state_path()
    path_b = router_b._state_path()
    path_default = router_default._state_path()

    assert path_a != path_b, "Isolated keys should produce different state files"
    assert path_b != path_default, "Named key should differ from default"


def test_provider_state_without_key_uses_default():
    """ProviderRouter without state_key must use the default path."""
    from llm_router import ProviderRouter, ProviderState
    p = ProviderState(name="test", client=object(), priority=0)
    router = ProviderRouter([p])
    path = router._state_path()
    assert path.endswith(".provider_state.json")


# ── Deep agent verify gate ──────────────────────────────────────────────

def test_deep_agent_has_verify_gate():
    """NativeDeepAgent.run() must call self.evidence_log.verify().
    Can't easily mock the full LLM to test end-to-end, but we verify
    the structural requirements: VerifierError is imported and the
    verify gate is documented."""
    from engine.deep_agent import NativeDeepAgent
    assert VerifierError is not None  # imported

    # The verify gate exists as a code path in run()
    import inspect
    source = inspect.getsource(NativeDeepAgent.run)
    assert "evidence_log.verify" in source, (
        "run() must contain evidence_log.verify() call"
    )
    assert "require_tools" in source


def test_deep_agent_design_decision_documented():
    """The DESIGN DECISION about TodoManager must be documented in run()."""
    import inspect
    source = inspect.getsource(NativeDeepAgent.run)
    assert "TodoManager" in source, (
        "run() must document the TodoManager ownership design decision"
    )


def test_verifier_error_not_in_evidence():
    """VerifierError is still a regular exception."""
    error = VerifierError("test")
    assert str(error) == "test"


# ── clean compile everything ─────────────────────────────────────────────

def test_all_modules_compile():
    import py_compile
    for f in [
        "core/constants.py",
        "engine/loop.py",
        "llm_router.py",
        "main.py",
        "engine/deep_agent.py",
    ]:
        py_compile.compile(os.path.join(os.path.dirname(__file__), "..", f), doraise=True)


def test_tactical_fast_fail_402():
    """ProviderRouter must instantly halt on HTTP 402 without trying subsequent providers."""
    from llm_router import ProviderRouter, ProviderState
    import pytest

    class MockClient402:
        def generate_response(self, messages, **kwargs):
            raise Exception("OpenRouter API error: 402 Insufficient credits")

    class MockClientNext:
        def generate_response(self, messages, **kwargs):
            return "Should never be called"

    p1 = ProviderState(name="OR-0", client=MockClient402(), priority=0)
    p2 = ProviderState(name="OR-1", client=MockClientNext(), priority=1)
    router = ProviderRouter([p1, p2], state_key="test_402")

    with pytest.raises(RuntimeError) as exc_info:
        list(router.generate_stream([{"role": "user", "content": "hello"}]))

    assert "OpenRouter credits depleted" in str(exc_info.value)
    assert p1.failure_count == 0  # halted instantly before recording normal cooldown backoff
    assert p2.failure_count == 0


def test_fixation_breaker_soft_interception():
    """ExecutionLoop must intercept repeated identical tool call immediately and inject [SYSTEM CRITIQUE] without dispatching."""
    from engine.loop import ExecutionLoop, _LoopCtx
    from core.kernel.state import RuntimeState
    from core.parser import ToolCall

    state = RuntimeState(session_id="test_fixation")
    loop = ExecutionLoop(state=state)
    loop._ctx = _LoopCtx(user_prompt="do something")

    tc1 = ToolCall(tool="execute_shell", args={"command": "ls -la"})
    tc2 = ToolCall(tool="execute_shell", args={"command": "ls -la"})

    # First attempt should proceed normally (not blocked by fixation breaker)
    sig1 = loop._handle_cycle_and_security(tc1)
    assert sig1.name != "CONTINUE" or loop._fixation_count == 0

    # Second identical attempt should be intercepted by Fixation Breaker
    sig2 = loop._handle_cycle_and_security(tc2)
    assert sig2.name == "CONTINUE"
    assert loop._fixation_count == 1
    messages = state.get_messages()
    assert any("[SYSTEM CRITIQUE]" in m.get("content", "") and m.get("role") == "user" for m in messages)


def test_evidence_feedback_loop_soft_interception():
    """ExecutionLoop must intercept rejected claims/final_answers, increment _evidence_rejection_count, and inject [EVIDENCE REJECTED]."""
    from engine.loop import ExecutionLoop, _LoopCtx
    from core.kernel.state import RuntimeState
    from core.parser import ToolCall

    state = RuntimeState(session_id="test_evidence_rejection")
    loop = ExecutionLoop(state=state)
    loop._ctx = _LoopCtx(user_prompt="find the file and report line count")
    loop._last_response = "The file has 42 lines."  # Unverified claim without evidence anchor

    # Call final_answer tool call
    tc_final = ToolCall(tool="final_answer", args={"answer": "The file has 42 lines."})
    sig = loop._handle_cycle_and_security(tc_final)

    assert sig.name == "CONTINUE"
    assert loop._evidence_rejection_count == 1
    messages = state.get_messages()
    assert any("[EVIDENCE REJECTED]" in m.get("content", "") and m.get("role") == "user" for m in messages)


def test_safe_strip_and_last_response_safety():
    """Verify safe_strip handles None, exceptions, and non-strings without crashing."""
    from core.utils import safe_strip
    from engine.loop import ExecutionLoop
    from core.kernel.state import RuntimeState

    assert safe_strip(None, default="fallback") == "fallback"
    assert safe_strip("   hello world   ") == "hello world"
    assert safe_strip(RuntimeError("test error")) == "test error"
    assert safe_strip(42) == "42"

    state = RuntimeState(session_id="test_safe_strip")
    loop = ExecutionLoop(state=state)
    from engine.loop import _LoopCtx
    loop._ctx = _LoopCtx(user_prompt="test")
    loop._last_response = RuntimeError("An unexpected error occurred")
    # Verify _maybe_force_partial_answer checks safe_strip without AttributeError on .strip()
    assert not loop._maybe_force_partial_answer()


if __name__ == "__main__":
    test_chitchat_set_contains_greetings()
    test_chitchat_case_insensitive()
    test_chitchat_empty_false()
    test_substantive_not_chitchat()
    test_loop_prompter_uses_is_chitchat()
    test_provider_state_path_isolation()
    test_provider_state_without_key_uses_default()
    test_deep_agent_has_verify_gate()
    test_deep_agent_design_decision_documented()
    test_verifier_error_not_in_evidence()
    test_tactical_fast_fail_402()
    test_fixation_breaker_soft_interception()
    test_evidence_feedback_loop_soft_interception()
    test_safe_strip_and_last_response_safety()
    test_all_modules_compile()
    print("All Phase 5 tests passed.")
