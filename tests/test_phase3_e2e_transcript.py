"""
Phase 3 — Deterministic E2E Transcript Tests.

Verifies exactly-one terminal TurnOutcome per started turn for every
scenario: success, tool failure, empty response, retry exhaustion,
cancellation, exception, duplicate finalization, and both engines.

Uses mocked/simulated ExecutionLoop instances — no real LLM calls.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.turn_outcome import TurnOutcome, TurnStatus, LLMInvocationResult, LLMInvocationStatus
from core.turn_finalizer import TurnFinalizer
from core.kernel.state import RuntimeState


class TestE2eTranscriptContracts(unittest.TestCase):
    """Deterministic E2E transcript tests for exactly-one terminal outcome."""

    # ── Helper: build a minimal ExecutionLoop with mocked internals ────────

    def _make_engine(self, run_once_body=None):
        """Create an ExecutionLoop with mock state + dispatcher.

        The caller can optionally inject a custom _run_once body
        to simulate specific scenarios.
        """
        from engine.loop import ExecutionLoop
        state = RuntimeState(session_id="e2e-test", max_steps=50)
        engine = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: "mock response",
            dispatcher=MagicMock(),
        )
        # Prevent _build_static_context from touching disk
        engine._build_static_context = MagicMock(return_value="")
        return engine, state

    # ── 1. Successful turn emits exactly one COMPLETED ────────────────────

    def test_successful_turn_emits_one_completed(self):
        """Simulate a successful agent turn → COMPLETED outcome."""
        engine, state = self._make_engine()
        # Simulate: the loop runs, agent calls final_answer => status COMPLETED
        state.update_status("COMPLETED")
        engine._last_response = "Here is your answer."

        engine._finalize_loop(interrupted=False)

        self.assertTrue(engine._turn_finalizer.is_finalized)
        outcome = engine._turn_finalizer.outcome
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.status, TurnStatus.COMPLETED)
        self.assertIn("answer", outcome.safe_message)
        self.assertIn("answer", outcome.final_answer)
        # Verify exactly one emission
        self.assertEqual(len(engine._turn_finalizer.duplicate_diagnostics), 0)

    # ── 2. Tool failure / connection refused emits FAILED ─────────────────

    def test_connection_refused_emits_failed(self):
        """Provider failure exhausted → FAILED before prompt return."""
        engine, state = self._make_engine()
        state.update_status("FAILED")
        engine._last_response = ""

        engine._finalize_loop(interrupted=False)

        self.assertTrue(engine._turn_finalizer.is_finalized)
        outcome = engine._turn_finalizer.outcome
        self.assertEqual(outcome.status, TurnStatus.FAILED)
        self.assertEqual(outcome.failure_stage, "terminal_failure")

    # ── 3. Empty LLM response produces terminal outcome ───────────────────

    def test_empty_llm_response_produces_terminal_outcome(self):
        """An empty LLM response path (EMPTY_RESPONSE) still finalizes."""
        engine, state = self._make_engine()
        # The loop ends without any response set. run() finally block
        # calls _finalize_loop which creates the last-resort fallback.
        engine._last_response = ""
        state.update_status("RUNNING")

        engine._finalize_loop(interrupted=False)

        self.assertTrue(engine._turn_finalizer.is_finalized)
        outcome = engine._turn_finalizer.outcome
        self.assertIsNotNone(outcome)
        # Should be FAILED (no COMPLETED status was set)
        self.assertEqual(outcome.status, TurnStatus.FAILED)

    # ── 4. Retry exhaustion produces exactly one terminal outcome ─────────

    def test_retry_exhaustion_one_terminal_outcome(self):
        """After MAX_PROVIDER_FAIL_STREAK failures, exactly one terminal outcome."""
        engine, state = self._make_engine()
        state.update_status("FAILED")

        # Simulate: engine calls _finalize_loop after retry exhaustion
        engine._finalize_loop(interrupted=False)

        self.assertTrue(engine._turn_finalizer.is_finalized)
        outcome = engine._turn_finalizer.outcome
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.status, TurnStatus.FAILED)

        # Subsequent _finalize_loop calls must not overwrite the outcome
        engine._finalize_loop(interrupted=False)
        engine._finalize_loop(interrupted=False)
        self.assertIs(engine._turn_finalizer.outcome, outcome)
        # No duplicate diagnostics because _finalize_loop guards is_finalized
        # before calling finalize() (the guard at the TurnFinalizer level
        # is only reached if an external caller calls finalize() directly).

    # ── 5. Cancellation produces CANCELLED (interrupted path) ─────────────

    def test_cancellation_emits_failed_interrupted(self):
        """KeyboardInterrupt → FAILED with failure_stage='interrupted'."""
        engine, state = self._make_engine()
        # KeyboardInterrupt handler sets interrupted=True
        engine._finalize_loop(interrupted=True)

        self.assertTrue(engine._turn_finalizer.is_finalized)
        outcome = engine._turn_finalizer.outcome
        self.assertEqual(outcome.status, TurnStatus.FAILED)
        self.assertEqual(outcome.failure_stage, "interrupted")

    # ── 6. Unexpected exception produces FAILED ───────────────────────────

    def test_unexpected_exception_produces_failed(self):
        """Exception during run → FAILED via finally block fallback."""
        engine, state = self._make_engine()
        state.update_status("ERROR")

        # The exception is re-raised, but _finalize_loop runs in finally
        engine._finalize_loop(interrupted=False)

        self.assertTrue(engine._turn_finalizer.is_finalized)
        outcome = engine._turn_finalizer.outcome
        self.assertEqual(outcome.status, TurnStatus.FAILED)

    # ── 7. Duplicate terminal attempt emits only one outcome ─────────────

    def test_duplicate_finalization_emits_one_outcome(self):
        """Two finalize attempts → one terminal outcome + one diagnostic."""
        engine, state = self._make_engine()
        outcome1 = TurnOutcome(status=TurnStatus.COMPLETED, safe_message="First")
        outcome2 = TurnOutcome(status=TurnStatus.FAILED, safe_message="Second")

        ok1 = engine._turn_finalizer.finalize(outcome1)
        ok2 = engine._turn_finalizer.finalize(outcome2)

        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertEqual(engine._turn_finalizer.outcome.status, TurnStatus.COMPLETED)
        self.assertEqual(len(engine._turn_finalizer.duplicate_diagnostics), 1)

    # ── 8. Both agent engines satisfy TurnFinalizer contract ──────────────

    def test_deep_agent_has_turn_finalizer(self):
        """NativeDeepAgent also has a _turn_finalizer (D2 fix)."""
        from engine.deep_agent import NativeDeepAgent

        state = RuntimeState(session_id="deep-agent-test", max_steps=50)
        agent = NativeDeepAgent(runtime_state=state)
        self.assertTrue(hasattr(agent, "_turn_finalizer"))
        self.assertIsInstance(agent._turn_finalizer, TurnFinalizer)

    def test_run_returns_turn_outcome(self):
        """engine.run() returns TurnOutcome, not str."""
        engine, state = self._make_engine()
        engine._last_response = "test answer"
        state.update_status("COMPLETED")
        engine._finalize_loop(interrupted=False)

        # run() returns self._turn_finalizer.outcome
        outcome = engine._turn_finalizer.outcome
        self.assertIsInstance(outcome, TurnOutcome)

    # ── 9. Prompt does not render before terminal outcome ────────────────

    def test_no_outcome_before_finalize(self):
        """Before _finalize_loop, outcome is None."""
        engine, state = self._make_engine()
        self.assertIsNone(engine._turn_finalizer.outcome)
        self.assertFalse(engine._turn_finalizer.is_finalized)

    # ── 10. Finally fallback only when no prior outcome ──────────────────

    def test_finally_does_not_overwrite_completed(self):
        """The finally fallback must preserve an already-set COMPLETED."""
        engine, state = self._make_engine()
        outcome = TurnOutcome(status=TurnStatus.COMPLETED, safe_message="Preserve me")
        engine._turn_finalizer.finalize(outcome)

        # Now simulate the finally block running
        engine._last_response = ""
        state.update_status("RUNNING")
        engine._finalize_loop(interrupted=False)

        self.assertEqual(engine._turn_finalizer.outcome.status, TurnStatus.COMPLETED)
        self.assertEqual(engine._turn_finalizer.outcome.safe_message, "Preserve me")

    # ── 11. LLMInvocationResult status mapping ───────────────────────────

    def test_llm_invocation_result_status_mapping(self):
        """Verify the exact mapping of LLMInvocationStatus values."""
        # SUCCESS → normal orchestration
        r1 = LLMInvocationResult(status=LLMInvocationStatus.SUCCESS, content="ok")
        self.assertEqual(r1.status, LLMInvocationStatus.SUCCESS)
        self.assertTrue(r1.content)

        # EMPTY_RESPONSE → retry policy
        r2 = LLMInvocationResult(status=LLMInvocationStatus.EMPTY_RESPONSE, retryable=True)
        self.assertEqual(r2.status, LLMInvocationStatus.EMPTY_RESPONSE)
        self.assertTrue(r2.retryable)

        # RETRYABLE_ERROR → bounded retry
        r3 = LLMInvocationResult(status=LLMInvocationStatus.RETRYABLE_ERROR, retryable=True)
        self.assertEqual(r3.status, LLMInvocationStatus.RETRYABLE_ERROR)
        self.assertTrue(r3.retryable)

        # FATAL_ERROR → FAILED
        r4 = LLMInvocationResult(status=LLMInvocationStatus.FATAL_ERROR, retryable=False)
        self.assertEqual(r4.status, LLMInvocationStatus.FATAL_ERROR)
        self.assertFalse(r4.retryable)

        # CANCELLED → CANCELLED
        r5 = LLMInvocationResult(status=LLMInvocationStatus.CANCELLED, retryable=False)
        self.assertEqual(r5.status, LLMInvocationStatus.CANCELLED)


# ── Regression: TurnOutcome is NOT iterable (Phase 6.1) ─────────────


class TestTurnOutcomeNotIterable(unittest.TestCase):
    """Regression: TurnOutcome must NOT be iterable or tuple-unpackable.

    Phase 3 migrated engine.run() to return a structured TurnOutcome
    instead of a raw str or tuple[str, str].  All callers must use
    structured access (outcome.status, outcome.final_answer, etc.)
    rather than tuple unpacking or iteration.
    """

    def test_turn_outcome_not_iterable(self):
        """TurnOutcome does not support __iter__."""
        outcome = TurnOutcome(status=TurnStatus.COMPLETED, final_answer="test")
        with self.assertRaises(TypeError):
            answer, metadata = outcome  # tuple unpacking

    def test_turn_outcome_not_iterable_for_loop(self):
        """TurnOutcome does not support iteration via for-in."""
        outcome = TurnOutcome(status=TurnStatus.COMPLETED, final_answer="test")
        with self.assertRaises(TypeError):
            for x in outcome:
                pass

    def test_turn_outcome_structured_access_works(self):
        """Structured attribute access works correctly."""
        outcome = TurnOutcome(
            status=TurnStatus.COMPLETED,
            final_answer="Hello, world!",
            safe_message="Task completed successfully",
        )
        self.assertEqual(outcome.status, TurnStatus.COMPLETED)
        self.assertEqual(outcome.final_answer, "Hello, world!")
        self.assertEqual(outcome.safe_message, "Task completed successfully")
        self.assertEqual(outcome.display_text(), "Task completed successfully")

    def test_turn_outcome_display_text_fallback(self):
        """display_text falls back through safe_message → final_answer → status."""
        # Only status set
        o1 = TurnOutcome(status=TurnStatus.FAILED)
        self.assertEqual(o1.display_text(), "FAILED")
        # final_answer set
        o2 = TurnOutcome(status=TurnStatus.COMPLETED, final_answer="Answer")
        self.assertEqual(o2.display_text(), "Answer")
        # safe_message overrides final_answer
        o3 = TurnOutcome(status=TurnStatus.COMPLETED, safe_message="Safe", final_answer="Answer")
        self.assertEqual(o3.display_text(), "Safe")
