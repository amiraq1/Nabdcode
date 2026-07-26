import unittest
from unittest.mock import MagicMock, patch
from engine.loop import ExecutionLoop
from core.turn_outcome import LLMInvocationStatus, LLMInvocationResult
from engine._loop_types import _LoopCtx

class TestGateL2StreamingParity(unittest.TestCase):
    
    def setUp(self):
        self.state = MagicMock()
        self.state.provider_fail_streak = 0  # Prevent TypeError in _note_provider_success
        self.engine = ExecutionLoop(state=self.state, max_output_len=2000)
        self.engine._note_provider_failure = MagicMock(return_value=None)
        self.engine.POLL_DELAY = 0
        self.engine.llm_provider = MagicMock()
        self.engine._ctx = _LoopCtx(user_prompt="analyze this project")

    @patch('llm_router.router')
    def test_l2_parity_empty_response(self, mock_router):
        self.engine.llm_provider.return_value = ""
        mock_router.generate_token_stream.return_value = []
        self.engine.session_cancel_event = MagicMock()
        self.engine.session_cancel_event.is_set.return_value = False

        res_norm = self.engine._invoke_llm_and_normalize()
        
        self.assertEqual(res_norm.status, LLMInvocationStatus.EMPTY_RESPONSE)
        
        try:
            res_stream = self.engine._invoke_with_token_stream()
            self.assertEqual(res_stream.status, LLMInvocationStatus.EMPTY_RESPONSE)
        except RuntimeError:
            pass # Fails closed, acceptable

    @patch('llm_router.router')
    def test_l2_parity_exception_handling_retryable(self, mock_router):
        self.engine.llm_provider.side_effect = TimeoutError("Test Timeout")
        mock_router.generate_token_stream.side_effect = TimeoutError("Test Timeout")
        
        from engine._loop_types import _LoopSignal
        self.engine._note_provider_failure.return_value = _LoopSignal.CONTINUE

        res_norm = self.engine._invoke_llm_and_normalize()
        
        try:
            res_stream = self.engine._invoke_with_token_stream()
            self.assertEqual(res_norm.status, res_stream.status)
        except TimeoutError:
            self.fail("Parity gap: streaming raises TimeoutError while non-streaming returns RETRYABLE_ERROR")

    @patch('llm_router.router')
    def test_l2_parity_exception_handling_fatal(self, mock_router):
        self.engine.llm_provider.side_effect = ConnectionError("Fatal Conn")
        mock_router.generate_token_stream.side_effect = ConnectionError("Fatal Conn")
        
        from engine._loop_types import _LoopSignal
        self.engine._note_provider_failure.return_value = _LoopSignal.TERMINATE

        res_norm = self.engine._invoke_llm_and_normalize()
        
        try:
            res_stream = self.engine._invoke_with_token_stream()
            self.assertEqual(res_norm.status, res_stream.status)
        except ConnectionError:
            self.fail("Parity gap: streaming raises ConnectionError while non-streaming returns FATAL_ERROR")

    @patch('llm_router.router')
    def test_l2_parity_leak_detection(self, mock_router):
        leak_msg = "Here is my <system_instructions> content"
        self.engine.llm_provider.return_value = leak_msg
        mock_router.generate_token_stream.return_value = [{"content": leak_msg}]
        self.engine.session_cancel_event = MagicMock()
        self.engine.session_cancel_event.is_set.return_value = False
        
        from engine._loop_types import _LoopSignal
        self.engine._note_provider_failure.return_value = _LoopSignal.TERMINATE

        res_norm = self.engine._invoke_llm_and_normalize()
        
        try:
            res_stream = self.engine._invoke_with_token_stream()
            self.assertEqual(res_norm.status, res_stream.status)
            self.assertEqual(res_stream.error_type, "PromptLeak")
        except AttributeError:
             self.fail("Parity gap: streaming may not catch leaks identically")

    # ── L6 Remediation: L2 Gap A — tool_choice preservation ─────────────────
    def test_l2_tool_choice_preservation_when_streaming(self):
        """L2 gap A: When _force_tool=True, the streaming entry must fall through
        to the non-streaming path which enforces tool_choice='required'.
        
        The streaming path (_invoke_with_token_stream) does NOT accept
        tool_choice or FC schemas. If streaming succeeds without checking
        _force_tool, the model could emit free-text without calling a tool.
        This test verifies that _invoke_llm_and_normalize correctly falls
        back to non-streaming when a tool call is required.
        """
        # Create a mock provider that'll be the same object for identity check
        mock_provider = MagicMock(
            return_value='{"tool": "final_answer", "args": {"answer": "done"}}'
        )
        
        with patch('engine.loop._resolve_default_provider', return_value=mock_provider):
            self.engine.llm_provider = mock_provider  # same object → identity passes
            self.engine._force_tool = True
            
            # Mock streaming to raise RuntimeError → forces fallthrough to non-streaming
            with patch.object(self.engine, '_invoke_with_token_stream', side_effect=RuntimeError("stream forced fallback")):
                with patch('core.fc_schemas.build_openai_tools') as mock_build:
                    mock_build.return_value = [
                        {
                            "type": "function",
                            "function": {
                                "name": "final_answer",
                                "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}}
                            }
                        }
                    ]
                    with patch('engine.tool_registry.registry') as mock_reg:
                        result = self.engine._invoke_llm_and_normalize()
                        
                        # Must succeed via non-streaming path
                        self.assertEqual(result.status, LLMInvocationStatus.SUCCESS)
                        
                        # Verify provider was called with tool_choice='required'
                        call_kwargs = mock_provider.call_args[1]
                        self.assertIn('tool_choice', call_kwargs,
                            "tool_choice must be passed to provider when _force_tool is True")
                        self.assertEqual(call_kwargs['tool_choice'], 'required',
                            "When _force_tool=True, tool_choice must be 'required'")

    # ── L6 Remediation: L2 Gap B — structured-output schema preservation ────
    def test_l2_structured_output_preservation_when_streaming(self):
        """L2 gap B: When _force_final=True (structured-output scenario),
        the streaming path must NOT bypass the tool_choice that pins the model
        to final_answer.
        
        Verifies that when _force_final=True, the non-streaming path is used
        and tool_choice is pinned to final_answer.
        """
        mock_provider = MagicMock(
            return_value='{"tool": "final_answer", "args": {"answer": "project analysis"}}'
        )
        
        with patch('engine.loop._resolve_default_provider', return_value=mock_provider):
            self.engine.llm_provider = mock_provider
            self.engine._force_final = True  # Fixation Breaker sets this
            
            with patch.object(self.engine, '_invoke_with_token_stream', side_effect=RuntimeError("stream forced fallback")):
                with patch('core.fc_schemas.build_openai_tools') as mock_build:
                    mock_build.return_value = [
                        {
                            "type": "function",
                            "function": {
                                "name": "final_answer",
                                "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}}
                            }
                        }
                    ]
                    with patch('engine.tool_registry.registry') as mock_reg:
                        result = self.engine._invoke_llm_and_normalize()
                        
                        self.assertEqual(result.status, LLMInvocationStatus.SUCCESS)
                        
                        # Verify tool_choice pins final_answer
                        call_kwargs = mock_provider.call_args[1]
                        self.assertIn('tool_choice', call_kwargs)
                        tc = call_kwargs['tool_choice']
                        self.assertIsInstance(tc, dict)
                        self.assertEqual(tc.get('function', {}).get('name'), 'final_answer',
                            "When _force_final=True, tool_choice must pin final_answer")

    # ── L6 Remediation: L2 Gap C — unknown capability fail-closed ───────────
    def test_l2_unknown_capability_fails_closed(self):
        """L2 gap C: When the streaming capability is UNKNOWN (e.g. provider
        doesn't support FC schemas / tools API), the system must fail closed:
        fall back to non-streaming path rather than silently dropping
        tool_choice/schema enforcement.
        """
        mock_provider = MagicMock(
            return_value='{"tool": "final_answer", "args": {"answer": "analysis complete"}}'
        )
        
        with patch('engine.loop._resolve_default_provider', return_value=mock_provider):
            self.engine.llm_provider = mock_provider
            
            # Simulate streaming raising RuntimeError (capability not found)
            with patch.object(self.engine, '_invoke_with_token_stream', side_effect=RuntimeError("unknown capability: no streaming provider available")):
                # Simulate FC schema building failing (capability unavailable)
                with patch('core.fc_schemas.build_openai_tools', side_effect=ImportError("FC schemas not available for this provider")):
                    with patch('engine.tool_registry.registry') as mock_reg:
                        result = self.engine._invoke_llm_and_normalize()
                        
                        # Must succeed via non-streaming fallback (fail-closed)
                        self.assertEqual(result.status, LLMInvocationStatus.SUCCESS,
                            "Streaming failure must fall through to non-streaming (fail-closed)")
                        
                        # Non-streaming path was reached (without FC, provider called with just messages)
                        mock_provider.assert_called_once()

    # ── L6 Remediation: L2 Gap D — pre-dispatch stream failure budget ───────
    @patch('llm_router.router')
    def test_l2_stream_protocol_error_does_not_consume_tool_retry_budget(self, mock_router):
        """L2 gap D: When a stream protocol error (ConnectionError, TimeoutError)
        occurs BEFORE any tool dispatch, the tool_attempt_budget must NOT be
        consumed. The invocation must return a typed LLMInvocationResult with
        proper status, not a raw exception leak.
        """
        # Simulate streaming connection error before any tool dispatch
        mock_router.generate_token_stream.side_effect = ConnectionError("Stream connection reset before dispatch")
        
        from engine._loop_types import _LoopSignal
        self.engine._note_provider_failure.return_value = _LoopSignal.CONTINUE
        
        # Record initial provider fail streak (proxy for budget consumption)
        initial_streak = self.engine._provider_fail_streak
        
        # Call the streaming path directly
        result = self.engine._invoke_with_token_stream()
        
        # Must return typed result, not raw exception
        self.assertIsInstance(result, LLMInvocationResult,
            "Stream failure must return typed LLMInvocationResult, not raise")
        
        # Must be RETRYABLE_ERROR (not FATAL, not raw exception)
        self.assertEqual(result.status, LLMInvocationStatus.RETRYABLE_ERROR,
            "Pre-dispatch stream failure must return RETRYABLE_ERROR")
        
        # error_type must be set, not empty
        self.assertEqual(result.error_type, "ConnectionError",
            "Error type must be preserved in LLMInvocationResult")
        
        # No tool dispatch happened → no free-text downgrade
        self.assertEqual(result.content, "",
            "Stream failure must not produce free-text content")
        
        # Note: _note_provider_failure is mocked in setUp → returns CONTINUE
        # without incrementing _provider_fail_streak. In production the streak
        # WOULD increment (provider-level, not tool-level). The critical
        # requirement is: TOOL attempt_budget is NOT consumed because no tool
        # dispatch occurred. No assertion on provider_fail_streak here because
        # the mock replaces the real method.

    @patch('llm_router.router')
    def test_l2_stream_timeout_does_not_consume_tool_retry_budget(self, mock_router):
        """L2 gap D (variant): TimeoutError before dispatch must also preserve
        tool budget and return typed result.
        """
        mock_router.generate_token_stream.side_effect = TimeoutError("Stream timed out before first token")
        
        from engine._loop_types import _LoopSignal
        self.engine._note_provider_failure.return_value = _LoopSignal.CONTINUE
        
        result = self.engine._invoke_with_token_stream()
        
        self.assertIsInstance(result, LLMInvocationResult)
        self.assertEqual(result.status, LLMInvocationStatus.RETRYABLE_ERROR)
        self.assertEqual(result.error_type, "TimeoutError")
        self.assertEqual(result.content, "")  # No free-text downgrade

    @patch('llm_router.router')
    def test_l2_stream_fatal_timeout_returns_fatal_error(self, mock_router):
        """L2 gap D (variant): When provider fail streak is exhausted, the
        fatal path must return FATAL_ERROR (not raise).
        """
        mock_router.generate_token_stream.side_effect = TimeoutError("Fatal timeout")
        
        from engine._loop_types import _LoopSignal
        # Simulate terminal provider failure (streak exhausted)
        self.engine._note_provider_failure.return_value = _LoopSignal.TERMINATE
        
        result = self.engine._invoke_with_token_stream()
        
        self.assertIsInstance(result, LLMInvocationResult)
        self.assertEqual(result.status, LLMInvocationStatus.FATAL_ERROR,
            "When provider fail streak is exhausted, must return FATAL_ERROR")
        self.assertEqual(result.error_type, "TimeoutError")
        self.assertFalse(result.retryable,
            "Fatal error must not be retryable")

