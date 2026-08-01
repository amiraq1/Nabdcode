import unittest
import ast
from unittest.mock import MagicMock, patch
from engine.loop import ExecutionLoop
from core.turn_outcome import LLMInvocationStatus
from engine._loop_types import _LoopSignal

class TestGateL4GodMethodPolicy(unittest.TestCase):
    
    def setUp(self):
        self.state = MagicMock()
        self.state.step_count = 1
        self.state.session_id = "test-sess"
        self.state.provider_fail_streak = 0
        self.engine = ExecutionLoop(state=self.state, max_output_len=2000)
        self.engine._logger = MagicMock()
        self.engine.evidence_log = MagicMock()
        self.engine._ctx = MagicMock()
        self.engine._ctx.intent_policy = MagicMock()
        self.engine._ctx.intent_policy.needs_investigation = False
        self.engine._ctx.intent_policy.minimum_reads = 3
        self.engine.POLL_DELAY = 0

    def test_no_unjustified_semantic_drift_in_invoke_llm_and_normalize(self):
        """
        Verify that _invoke_llm_and_normalize still returns LLMInvocationResult
        and hasn't been split into unrecognizable chunks or changed signatures.
        """
        # Ensure the method still exists
        self.assertTrue(hasattr(self.engine, "_invoke_llm_and_normalize"))
        # Ensure the fallback properties haven't drifted.
        # Check that it still returns an LLMInvocationResult
        self.engine.llm_provider = MagicMock(return_value="test response")
        self.engine.session_cancel_event = MagicMock()
        self.engine.session_cancel_event.is_set.return_value = False
        
        result = self.engine._invoke_llm_and_normalize()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, LLMInvocationStatus.SUCCESS)

    def test_l1_truth_table_rows_still_hold(self):
        """
        Verify that specific L1 truth table invariants are intact.
        e.g., _LoopSignal still has CONTINUE, TERMINATE, PROCEED.
        """
        self.assertTrue(hasattr(_LoopSignal, "CONTINUE"))
        self.assertTrue(hasattr(_LoopSignal, "TERMINATE"))
        self.assertTrue(hasattr(_LoopSignal, "PROCEED"))
        
        # Verify ast properties of the file to ensure no cosmetic extractions
        # in the middle of loop.py
        with open("engine/loop.py", "r") as f:
            tree = ast.parse(f.read())
        
        # Check if _invoke_llm_and_normalize is still a single function inside ExecutionLoop
        class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ExecutionLoop")
        method_node = next((n for n in class_node.body if isinstance(n, ast.FunctionDef) and n.name == "_invoke_llm_and_normalize"), None)
        self.assertIsNotNone(method_node, "Method _invoke_llm_and_normalize was incorrectly extracted or removed.")
        
        # Ensure it has a reasonable size (at least 50 lines, proving it wasn't trivially decomposed)
        # It used to be roughly 150+ lines.
        length = method_node.end_lineno - method_node.lineno
        self.assertTrue(length > 50, f"Method is suspiciously small ({length} lines), indicating unjustified decomposition.")

    @patch('llm_router.router')
    def test_l2_parity_contract_still_holds(self, mock_router):
        """
        Verify that the L2 remediation works:
        streaming exception parity is strictly maintained.
        """
        self.engine.llm_provider = MagicMock(side_effect=TimeoutError("T"))
        mock_router.generate_token_stream.side_effect = TimeoutError("T")
        
        self.engine._note_provider_failure = MagicMock(return_value=_LoopSignal.CONTINUE)
        
        res_norm = self.engine._invoke_llm_and_normalize()
        res_stream = self.engine._invoke_with_token_stream()
        
        self.assertEqual(res_norm.status, LLMInvocationStatus.RETRYABLE_ERROR)
        self.assertEqual(res_norm.status, res_stream.status)

    @patch('engine._loop_helpers._prompt_requires_investigation', return_value=True)
    @patch('engine._loop_helpers._has_active_goal', return_value=True)
    @patch('core.convergence_gate.can_finalize')
    def test_l3_convergence_contract_still_holds(self, mock_can, mock_goal, mock_inv):
        """
        Verify L3 convergence threshold holds.
        """
        self.engine._real_reads = MagicMock(return_value=2)
        mock_can.return_value.allowed = True
        
        result = self.engine._emit_final("I think the answer is X", "natural_completion")
        self.assertFalse(result, "L3 contract drift: returned True for < 3 reads")
        self.assertTrue(self.engine._force_tool, "L3 contract drift: force_tool not set on rejection")
