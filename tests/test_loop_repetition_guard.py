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

    def test_thought_only_block_ban_triggers_kill_switch(self):
        """يتأكد أن الرد المكون فقط من Thought بدون أداة يتم إيقافه فوراً في أول محاولة."""
        state = RuntimeState(session_id="test-thought-ban")
        mock_llm = MagicMock(return_value="Thought for 2s")
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

        loop.run("Hello test")

        self.assertEqual(mock_llm.call_count, 1)
        loop._safe_shutdown.assert_called_once()
        args, _ = loop._safe_shutdown.call_args
        self.assertIn("only 'Thinking' blocks without tools", args[1])

    def test_normalized_fingerprint_catches_varying_thought_seconds(self):
        """يتأكد أن تغير ثواني التفكير في Thought for Xs لا يخدع نظام كشف التكرار."""
        state = RuntimeState(session_id="test-norm-fingerprint")
        responses = [
            "Thought for 1s\nExact same repeated hallucinated response body that repeats over and over.",
            "Thought for 2s\nExact same repeated hallucinated response body that repeats over and over.",
            "Thought for 8s\nExact same repeated hallucinated response body that repeats over and over.",
        ]
        mock_llm = MagicMock(side_effect=responses)
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

        loop.run("Hello test")

        self.assertEqual(mock_llm.call_count, 3)
        loop._safe_shutdown.assert_called_once()
        args, _ = loop._safe_shutdown.call_args
        self.assertIn("Infinite Replication Loop Detected", args[1])

    def test_bullet_tolerant_thought_ban_triggers_kill_switch(self):
        """يتأكد أن الردود المبدوءة بنجمة أو عبارات التفكير المعتادة يتم حظرها عند عدم وجود أداة."""
        for prompt_text in [
            "* Thought for 3 seconds",
            "  * Thinking through the problem.",
            "I will now think about that.",
        ]:
            state = RuntimeState(session_id="test-bullet-ban")
            mock_llm = MagicMock(return_value=prompt_text)
            loop = ExecutionLoop(llm_provider=mock_llm, state=state)
            loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

            loop.run("Hello test")

            self.assertEqual(mock_llm.call_count, 1)
            loop._safe_shutdown.assert_called_once()
            args, _ = loop._safe_shutdown.call_args
            self.assertIn("only 'Thinking' blocks without tools (bullet/star detected)", args[1])


if __name__ == "__main__":
    unittest.main()
