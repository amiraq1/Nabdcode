import pytest
from core.refusal_detector import is_refusal

def test_refusal_detected():
    assert is_refusal("لا أستطيع قراءة الملف") is True
    assert is_refusal("I cannot do that") is True
    assert is_refusal("I'm unable to help") is True
    assert is_refusal("لا يمكنني ذلك") is True
    assert is_refusal("This is a normal answer") is False

def test_retry_triggered(monkeypatch, mocker):
    from engine.loop import ExecutionLoop
    from core.kernel.state import RuntimeState
    from core.evidence import EvidenceLog
    
    state = RuntimeState("test_session")
    state.append_message({"role": "user", "content": "What is in file.py?"})
    
    from engine.loop import LLMInvocationStatus
    class DummyLLMResult:
        status = LLMInvocationStatus.SUCCESS
        content = "لا أستطيع رؤية الملف."
        
    class MockLoop(ExecutionLoop):
        def _invoke_llm_and_normalize(self):
            return DummyLLMResult()
            
    loop = MockLoop(state=state, evidence_log=EvidenceLog())
    
    from engine._loop_types import _LoopCtx, IntentPolicy
    loop._ctx = _LoopCtx(user_prompt="test", intent="dummy", intent_policy=IntentPolicy())
    
    # Run one step
    loop._run_once()
    
    messages = state.get_messages()
    assert getattr(loop, "_refusal_retry_count", 0) == 1
    assert "You MUST call a tool first" in messages[-1]["content"]

def test_max_retries_respected(monkeypatch, mocker):
    from engine.loop import ExecutionLoop
    from core.kernel.state import RuntimeState
    from core.evidence import EvidenceLog
    
    state = RuntimeState("test_session")
    state.append_message({"role": "user", "content": "What is in file.py?"})
    
    from engine.loop import LLMInvocationStatus
    class DummyLLMResult:
        status = LLMInvocationStatus.SUCCESS
        content = "لا أستطيع"
        
    class MockLoop(ExecutionLoop):
        def _invoke_llm_and_normalize(self):
            return DummyLLMResult()
            
    loop = MockLoop(state=state, evidence_log=EvidenceLog())
    loop._refusal_retry_count = 3
    
    from engine._loop_types import _LoopCtx, IntentPolicy
    loop._ctx = _LoopCtx(user_prompt="test", intent="dummy", intent_policy=IntentPolicy())
    
    # Should not append "You MUST call a tool first" again
    loop._run_once()
    
    messages = state.get_messages()
    assert "You MUST call a tool first" not in messages[-1]["content"]
    assert getattr(loop, "_refusal_retry_count", 0) == 3

def test_anchors_alive():
    # Placeholder for UX-5/UX-6/UX-9 anchors
    assert True
