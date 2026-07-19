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

        loop.run("Check workspace files and fix bugs")

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

        loop.run("Check workspace files and fix bugs")

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


class TestFinalAnswerTermination(unittest.TestCase):
    def test_final_answer_terminates_without_tool_loop(self):
        """A casual 'hi' answered with final_answer must terminate in ONE step,
        not loop on 'Unknown tool final_answer' corrections."""
        from core.kernel.events import bus

        state = RuntimeState(session_id="test-final-answer")
        mock_llm = MagicMock(
            return_value='{"tool": "final_answer", "args": {"answer": "Hello! How can I help today?"}}'
        )
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

        completed = []

        def _capture(payload):
            completed.append(payload)
        unsub = bus.subscribe("loop_completed", _capture)
        try:
            loop.run("hi")
        finally:
            unsub()

        # Must have called the LLM exactly once — no correction storm.
        self.assertEqual(mock_llm.call_count, 1)
        # No evidence should be recorded (final_answer is not an executable tool).
        self.assertEqual(len(loop.evidence_log.records), 0)
        # The answer must be surfaced verbatim via loop_completed output, and the
        # loop must have cleanly completed (status COMPLETED).
        self.assertTrue(completed, "loop_completed must be emitted")
        self.assertEqual(completed[0]["output"], "Hello! How can I help today?")
        self.assertEqual(state.status, "COMPLETED")

    def test_final_answer_not_in_rejected_tool_prompts(self):
        """final_answer must bypass tool-schema validation, never emitting
        tool_validation_failed for it."""
        from core.kernel.events import bus

        state = RuntimeState(session_id="test-final-answer-no-reject")
        mock_llm = MagicMock(
            return_value='{"tool": "final_answer", "args": {"answer": "Hi!"}}'
        )
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)

        events = []

        def _on_tool_validation_failed(payload):
            events.append(payload)
        unsub = bus.subscribe("tool_validation_failed", _on_tool_validation_failed)
        try:
            loop.run("hi")
        finally:
            unsub()

        self.assertEqual(events, [], "final_answer must not be reported as a validation failure")


if __name__ == "__main__":
    unittest.main()
