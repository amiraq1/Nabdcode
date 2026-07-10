"""Unit and regression tests for Repetition Guard (Sliding Window + Entropy Check) in ExecutionLoop."""

import unittest
from unittest.mock import MagicMock
from engine.loop import ExecutionLoop
from engine.state import RuntimeState


class TestLoopRepetitionGuard(unittest.TestCase):
    def test_repetition_guard_triggers_kill_switch(self):
        """يتأكد أن تكرار نفس البصمة 3 مرات يفجر الحلقة اللانهائية فوراً ويتوقف بأمان."""
        state = RuntimeState(session_id="test-rep-guard")
        # Mock LLM provider that returns the exact same string repeatedly
        repeated_response = "I will repeat this exact response forever to cause an infinite loop. " * 5
        mock_llm = MagicMock(return_value=repeated_response)

        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        # Ensure safe shutdown returns cleanly
        loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

        loop.run("Hello test")

        # LLM should be called exactly 3 times (1st appearance, 2nd appearance, 3rd appearance triggers kill switch)
        self.assertEqual(mock_llm.call_count, 3)
        loop._safe_shutdown.assert_called_once()
        args, _ = loop._safe_shutdown.call_args
        self.assertIn("Infinite Replication Loop Detected", args[1])


if __name__ == "__main__":
    unittest.main()
