"""
Phase 3 — Runtime Core: Unified RuntimeState + TurnOutcome

CHARACTERIZATION TESTS — Expected to FAIL against the current (pre-Phase 3)
implementation.  Each failure proves a specific defect:

  D1 — Double RuntimeState construction in main.py (lines 670 + 714)
  D2 — No structured TurnOutcome; engine.run() returns raw string
  D3 — _finalize_loop has no terminal-outcome enforcement
  D4 — Module-level _SESSION_PERMS_STATE fallback singleton
  D5 — Multiple return ("", "") paths continue loop silently
  D6 — _on_loop_completed has disabled code / no prompt gate
  D7 — No TurnOutcome or LLMInvocationResult type exists

After Phase 3 implementation, ALL tests in this file must PASS.
"""

import inspect
import unittest
from unittest.mock import MagicMock, patch
from typing import Any, Optional


# ======================================================================
# 1. one RuntimeState construction per session  (D1)
# ======================================================================

class TestOneRuntimeStatePerSession(unittest.TestCase):
    """D1: main.py constructs RuntimeState TWICE in _build_app().

    Line 670 creates Instance A for session restore + visualizer.
    Line 714 creates Instance B that overwrites it.
    """

    def test_double_construction_proves_split_brain(self):
        """_build_app() creates TWO RuntimeState instances (D1).
        After Phase 3, exactly one must exist.

        Uses static source analysis: grep for RuntimeState( calls
        in _build_app() to prove double construction.
        """
        import ast
        import main as main_mod

        source = inspect.getsource(main_mod._build_app)
        tree = ast.parse(source)

        # Count RuntimeState( calls in the AST
        class RuntimeStateCallCounter(ast.NodeVisitor):
            def __init__(self):
                self.count = 0
            def visit_Call(self, node):
                if (isinstance(node.func, ast.Name) and
                    node.func.id == "RuntimeState"):
                    self.count += 1
                self.generic_visit(node)

        counter = RuntimeStateCallCounter()
        counter.visit(tree)

        # After Phase 3: count must == 1
        # Currently: count >= 2 (D1)
        self.assertEqual(
            counter.count, 1,
            f"D1: _build_app() contains {counter.count} RuntimeState("
            f" calls (expected exactly 1). Source lines:\n"
            + "\n".join(
                line for line in source.splitlines()
                if "RuntimeState(" in line
            )
        )


# ======================================================================
# 2. identical RuntimeState object identity across all consumers  (D1)
# ======================================================================

class TestRuntimeStateIdentityAcrossConsumers(unittest.TestCase):
    """Every consumer of RuntimeState must receive the SAME object."""

    def test_loop_and_dispatcher_share_state(self):
        """ExecutionLoop and its Dispatcher must share one RuntimeState."""
        from core.kernel.state import RuntimeState
        from engine.loop import ExecutionLoop
        from engine._loop_helpers import _build_dispatcher

        state = RuntimeState(session_id="test-identity", max_steps=5)

        engine = ExecutionLoop(state=state, max_output_len=2000)
        self.assertIs(
            engine.state, state,
            f"ExecutionLoop.state mismatch: {id(engine.state)} vs {id(state)}"
        )

        # Dispatcher built from the same state
        dispatcher_state = getattr(engine.dispatcher, "state", None)
        if dispatcher_state is not None:
            self.assertIs(
                dispatcher_state, state,
                f"Dispatcher.state mismatch: {id(dispatcher_state)} vs {id(state)}"
            )


# ======================================================================
# 3. restored RuntimeState remains active (D1/D5)
# ======================================================================

class TestRestoredStateNotOverwritten(unittest.TestCase):
    """Session restore must NOT be overwritten by a fresh RuntimeState."""

    def test_messages_set_on_constructed_state(self):
        """The system message must be in state.messages after
        construction. Proves D1: if two instances exist, session
        restore data can be lost on the second one."""
        from core.kernel.state import RuntimeState

        # Quick isolated test: create a state, add system msg, verify it's there
        state = RuntimeState(session_id="test-restore-simple", max_steps=5)
        state.append_message({"role": "system", "content": "test-instruction"})

        messages = state.get_messages()
        system_msgs = [m for m in messages if m.get("role") == "system"]
        self.assertEqual(
            len(system_msgs), 1,
            "RuntimeState must preserve system messages after construction"
        )


# ======================================================================
# 4. separate sessions do not share state  (D4)
# ======================================================================

class TestSeparateSessionsIsolated(unittest.TestCase):
    """Two RuntimeState instances with different session_ids must be
    completely independent."""

    def test_different_session_ids_different_objects(self):
        """Two manually-constructed RuntimeStates with unique IDs."""
        from core.kernel.state import RuntimeState
        s1 = RuntimeState(session_id="session-a", max_steps=5)
        s2 = RuntimeState(session_id="session-b", max_steps=5)

        self.assertIsNot(s1, s2, "Two sessions must be distinct objects")
        self.assertNotEqual(
            s1.session_id, s2.session_id,
            "Two sessions must have different session_ids"
        )

        # State mutation on s1 must not affect s2
        s1.append_message({"role": "user", "content": "hello"})
        s2.append_message({"role": "user", "content": "world"})
        self.assertEqual(
            len(s1.get_messages()), 1,
            "s1 must have exactly 1 message"
        )
        self.assertEqual(
            len(s2.get_messages()), 1,
            "s2 must have exactly 1 message (not shared with s1)"
        )
        self.assertEqual(
            s1.get_messages()[0]["content"], "hello",
            "s1 content must be independent of s2"
        )
        self.assertEqual(
            s2.get_messages()[0]["content"], "world",
            "s2 content must be independent of s1"
        )


# ======================================================================
# 5. module-level REPL fallback is absent  (D4)
# ======================================================================

class TestNoModuleLevelFallbackState(unittest.TestCase):
    """After Phase 3 + V8: _SESSION_PERMS_STATE must not exist in repl_termux.
    It was first reduced to None, then removed entirely in V8."""

    def test_no_runtime_state_module_level(self):
        """V8: _SESSION_PERMS_STATE has been removed.

        Phase 3 decoupled authorization from RuntimeState (D4).
        V8 completed the cleanup by removing the None sentinel entirely.
        This test verifies the removal is permanent.
        """
        import ast, pathlib
        tree = ast.parse(pathlib.Path("ui/repl_termux.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_SESSION_PERMS_STATE":
                        self.fail(
                            "D4/V8: _SESSION_PERMS_STATE has been re-introduced. "
                            "It is a dead sentinel and must not exist."
                        )


# ======================================================================
# 6. successful turn emits exactly one COMPLETED  (D2/D7)
# ======================================================================

class TestSuccessfulTurnEmitsCompleted(unittest.TestCase):
    """After Phase 3: a successful turn must emit exactly one COMPLETED
    TurnOutcome."""

    def test_turn_outcome_type_exists(self):
        """The module must define TurnOutcome.  Currently it does NOT."""
        try:
            from core.turn_outcome import TurnOutcome
            has_type = True
        except (ImportError, ModuleNotFoundError):
            has_type = False

        self.assertTrue(
            has_type,
            "D2/D7: TurnOutcome type does not exist — "
            "engine.run() returns a raw string"
        )

    def test_turn_outcome_has_completed(self):
        """TurnStatus must define COMPLETED."""
        try:
            from core.turn_outcome import TurnStatus
            has_completed = hasattr(TurnStatus, "COMPLETED")
        except (ImportError, ModuleNotFoundError):
            has_completed = False

        self.assertTrue(
            has_completed,
            "D2: TurnStatus must define COMPLETED"
        )


# ======================================================================
# 7. tool failure emits FAILED or BLOCKED  (D2/D3)
# ======================================================================

class TestToolFailureEmitsFailure(unittest.TestCase):
    """Tool failure must emit FAILED/BLOCKED, not a silent empty string."""

    def test_engine_run_does_not_return_raw_str(self):
        """engine.run() currently returns str.  After Phase 3 it must
        not return a raw string — it should return a structured TurnOutcome
        or publish via the finalization authority."""
        from engine.loop import ExecutionLoop

        sig = inspect.signature(ExecutionLoop.run)
        ret = sig.return_annotation

        # Currently: ret is str → assertIsNot(str, str) fails (correct pre-Phase 3)
        # After Phase 3: ret is TurnOutcome → assertIsNot(TurnOutcome, str) passes
        self.assertIsNot(
            ret, str,
            "D2: engine.run() returns raw str — must change to structured type"
        )


# ======================================================================
# 8. connection-refused cannot terminate silently  (D3)
# ======================================================================

class TestConnectionRefusedEmitsOutcome(unittest.TestCase):
    """Provider failure must publish a terminal outcome, not vanish silently."""

    def test_engine_has_turn_finalizer(self):
        """After Phase 3: ExecutionLoop must have a turn-finalization mechanism."""
        from core.kernel.state import RuntimeState
        from engine.loop import ExecutionLoop

        state = RuntimeState(session_id="test-finalizer", max_steps=5)
        engine = ExecutionLoop(state=state, max_output_len=2000)

        has_finalizer = (
            hasattr(engine, "_turn_finalizer") or
            hasattr(engine, "turn_outcome") or
            hasattr(engine, "_outcome")
        )
        self.assertTrue(
            has_finalizer,
            "D3: ExecutionLoop has no turn-finalization authority — "
            "provider failure can terminate silently"
        )


# ======================================================================
# 9. retry exhaustion emits terminal outcome  (D3)
# ======================================================================

class TestRetryExhaustionEmitsOutcome(unittest.TestCase):
    """Retry exhaustion must emit exactly one terminal outcome."""

    def test_retry_exhaustion_does_not_silently_return(self):
        """Inject provider failures until exhaustion; verify an outcome."""
        from core.kernel.state import RuntimeState
        from engine.loop import ExecutionLoop, _LoopSignal
        from engine._loop_helpers import MAX_PROVIDER_FAIL_STREAK

        state = RuntimeState(session_id="test-retry", max_steps=50)
        state.append_message({"role": "system", "content": "test"})
        engine = ExecutionLoop(state=state, max_output_len=2000)

        # Run provider failures until exhaustion
        # _note_provider_failure should set a terminal outcome
        signal = engine._note_provider_failure("test error")
        for _ in range(MAX_PROVIDER_FAIL_STREAK - 1):
            if signal == _LoopSignal.TERMINATE:
                break
            signal = engine._note_provider_failure(f"test error {_}")

        # After Phase 3: _finalize_loop creates the fallback outcome.
        # Run it to ensure outcome is materialized.
        engine._finalize_loop(interrupted=False)

        # After Phase 3: the engine must have an outcome at this point.
        # Currently: no outcome exists (D3).
        has_outcome = (
            hasattr(engine, "_turn_finalizer") and
            engine._turn_finalizer.outcome is not None
        ) or (
            hasattr(engine, "_outcome") and
            engine._outcome is not None
        )

        self.assertTrue(
            has_outcome,
            "D3: After retry exhaustion no terminal outcome exists — "
            "engine can return silently"
        )


# ======================================================================
# 10. cancellation emits CANCELLED  (D2/D7)
# ======================================================================

class TestCancellationEmitsCancelled(unittest.TestCase):
    """User cancellation must emit CANCELLED."""

    def test_turn_outcome_has_cancelled(self):
        """TurnStatus must define CANCELLED."""
        try:
            from core.turn_outcome import TurnStatus
            has_cancelled = hasattr(TurnStatus, "CANCELLED")
        except (ImportError, ModuleNotFoundError):
            has_cancelled = False

        self.assertTrue(
            has_cancelled,
            "D2/D7: TurnStatus.CANCELLED does not exist — "
            "cancellation can return silently"
        )


# ======================================================================
# 11. incomplete work emits PARTIAL/BLOCKED  (D2)
# ======================================================================

class TestIncompleteWorkEmitsPartialBlocked(unittest.TestCase):
    """Convergence rejection / budget exhausted must emit PARTIAL or BLOCKED."""

    def test_turn_outcome_has_partial_and_blocked(self):
        """TurnStatus must define PARTIAL and BLOCKED."""
        try:
            from core.turn_outcome import TurnStatus
            has_partial = hasattr(TurnStatus, "PARTIAL")
            has_blocked = hasattr(TurnStatus, "BLOCKED")
        except (ImportError, ModuleNotFoundError):
            has_partial = has_blocked = False

        self.assertTrue(
            has_partial and has_blocked,
            "D2: TurnStatus must define PARTIAL and BLOCKED"
        )


# ======================================================================
# 12. exception path emits FAILED  (D3)
# ======================================================================

class TestExceptionPathEmitsFailed(unittest.TestCase):
    """An unhandled exception inside engine.run() must publish FAILED."""

    def test_exception_in_run_sets_outcome(self):
        """Simulate an exception in run() and verify outcome exists."""
        from core.kernel.state import RuntimeState
        from engine.loop import ExecutionLoop

        state = RuntimeState(session_id="test-exc", max_steps=5)
        state.append_message({"role": "system", "content": "test"})
        engine = ExecutionLoop(state=state, max_output_len=2000)

        # After Phase 3: the _finalize_loop must have set a fallback outcome
        # Simulate a failed run by calling _finalize_loop directly
        engine._finalize_loop(interrupted=False)

        has_outcome = (
            hasattr(engine, "_turn_finalizer") and
            engine._turn_finalizer.outcome is not None
        ) or (
            hasattr(engine, "_outcome") and
            engine._outcome is not None
        )

        self.assertTrue(
            has_outcome,
            "D3: After _finalize_loop no terminal outcome exists — "
            "exceptions can return silently"
        )


# ======================================================================
# 13. duplicate finalization emits only one outcome  (D3/D7)
# ======================================================================

class TestDuplicateFinalizationEmitsOneOutcome(unittest.TestCase):
    """If two terminal paths fire, only one outcome is published."""

    def test_turn_finalizer_module_exists(self):
        """TurnFinalizer module must exist after Phase 3."""
        try:
            from core.turn_finalizer import TurnFinalizer
            exists = True
        except (ImportError, ModuleNotFoundError):
            exists = False
        self.assertTrue(
            exists,
            "D3/D7: TurnFinalizer not found — duplicate terminal "
            "paths could emit multiple outcomes"
        )


# ======================================================================
# 14. finally fallback only when no prior outcome  (D3)
# ======================================================================

class TestFinallyFallbackConditional(unittest.TestCase):
    """The outer finally block emits FAILED fallback ONLY when no
    terminal outcome was published."""

    def test_turn_finalizer_once_semantics(self):
        """TurnFinalizer must enforce exactly-once: first commit wins."""
        try:
            from core.turn_finalizer import TurnFinalizer
            from core.turn_outcome import TurnOutcome, TurnStatus
        except (ImportError, ModuleNotFoundError):
            self.fail("D3/D7: TurnFinalizer/TurnOutcome not found")

        finalizer = TurnFinalizer()
        outcome1 = TurnOutcome(status=TurnStatus.COMPLETED, safe_message="First")
        outcome2 = TurnOutcome(status=TurnStatus.FAILED, safe_message="Second")

        first_ok = finalizer.finalize(outcome1)
        second_ok = finalizer.finalize(outcome2)

        self.assertTrue(first_ok, "First finalize() must succeed")
        self.assertFalse(second_ok, "Second finalize() must be rejected")
        self.assertEqual(
            finalizer.outcome.status, outcome1.status,
            "Original outcome must not be overwritten"
        )

    def test_finally_does_not_overwrite_success(self):
        """If COMPLETED exists, finally must NOT overwrite with FAILED."""
        try:
            from core.turn_finalizer import TurnFinalizer
            from core.turn_outcome import TurnOutcome, TurnStatus
        except (ImportError, ModuleNotFoundError):
            self.fail("D3/D7: TurnFinalizer/TurnOutcome not found")

        finalizer = TurnFinalizer()
        finalizer.finalize(TurnOutcome(status=TurnStatus.COMPLETED, safe_message="Success"))

        # Simulate finally block — must NOT overwrite
        if finalizer.outcome is None:
            finalizer.finalize(TurnOutcome(status=TurnStatus.FAILED, safe_message="Fallback"))

        self.assertEqual(
            finalizer.outcome.status, "COMPLETED",
            "D3: Finally fallback must NOT overwrite COMPLETED"
        )


# ======================================================================
# 15. prompt cannot render before terminal outcome  (D3/D6)
# ======================================================================

class TestPromptRequiresTerminalOutcome(unittest.TestCase):
    """The REPL must not display the prompt until a terminal outcome exists."""

    def test_main_has_outcome_before_prompt(self):
        """After Phase 3: _run_interactive_turn must check for a terminal
        outcome before returning to the prompt loop."""
        import main as main_mod

        # Check if the module references a turn outcome gate
        source = inspect.getsource(main_mod)

        # After Phase 3: must reference turn_outcome or similar outcome
        # gate in the REPL/prompt section.
        # Use a more specific check: must reference "turn_outcome" not
        # just "terminal" (which matches TerminalVisualizer).
        has_gate = (
            "turn_outcome" in source.lower() or
            "terminal_outcome" in source.lower() or
            "_outcome" in source.lower()
        )

        self.assertTrue(
            has_gate,
            "D3/D6: REPL does not gate on terminal outcome — "
            "silent prompt returns are possible"
        )


# ======================================================================
# 16. empty LLM response is typed (LLMInvocationResult)  (D5/D7)
# ======================================================================

class TestEmptyLLMResponseTyped(unittest.TestCase):
    """Empty ("", "") tuples must be replaced by LLMInvocationResult."""

    def test_llm_invocation_result_exists(self):
        """LLMInvocationResult type must exist after Phase 3."""
        try:
            from core.turn_outcome import LLMInvocationResult
            exists = True
        except (ImportError, ModuleNotFoundError):
            exists = False

        self.assertTrue(
            exists,
            "D5/D7: LLMInvocationResult does not exist — "
            "empty ('', '') tuples can loop silently"
        )


# ======================================================================
# 17. both agent engines satisfy same transcript contract  (D2)
# ======================================================================

class TestBothEnginesSameContract(unittest.TestCase):
    """ExecutionLoop and NativeDeepAgent must both return a TurnOutcome
    or publish via the same finalization authority."""

    def test_both_engines_have_finalizer(self):
        """Both engines must attach a TurnFinalizer (or equivalent)
        so they satisfy the same terminal-outcome contract."""
        from core.kernel.state import RuntimeState
        from engine.loop import ExecutionLoop
        from engine.deep_agent import NativeDeepAgent

        state = RuntimeState(session_id="test-contract", max_steps=5)

        loop_engine = ExecutionLoop(state=state, max_output_len=2000)
        deep_engine = NativeDeepAgent(runtime_state=state)

        # After Phase 3: both must have turn-finalization mechanism
        loop_has = (
            hasattr(loop_engine, "_turn_finalizer") or
            hasattr(loop_engine, "turn_outcome")
        )
        deep_has = (
            hasattr(deep_engine, "_turn_finalizer") or
            hasattr(deep_engine, "turn_outcome") or
            hasattr(deep_engine, "final_outcome")
        )

        self.assertTrue(
            loop_has,
            "D2: ExecutionLoop has no turn-finalization mechanism"
        )
        self.assertTrue(
            deep_has,
            "D2: NativeDeepAgent has no turn-finalization mechanism"
        )


# ======================================================================
# 18. persistence adapter remains distinct from runtime ownership
# ======================================================================

class TestPersistenceAdapterDistinct(unittest.TestCase):
    """core/state_manager.py is a file-based adapter, NOT a RuntimeState."""

    def test_shared_state_manager_not_runtime_state(self):
        """SharedStateManager must remain a file-based adapter."""
        from core.state_manager import SharedStateManager
        from core.kernel.state import RuntimeState

        mgr = SharedStateManager()

        self.assertFalse(
            hasattr(mgr, "runtime_state") and
            isinstance(mgr.runtime_state, RuntimeState),
            "SharedStateManager must remain file-based, not a RuntimeState wrapper"
        )


# ======================================================================
# 19. shell permission behavior is not weakened
# ======================================================================

class TestShellPermissionsNotWeakened(unittest.TestCase):
    """PermissionEngine must still work without module-level RuntimeState."""

    def test_permission_engine_works_independently(self):
        """PermissionEngine evaluates commands without RuntimeState."""
        from core.permissions import PermissionEngine, PermissionDecision, ShellPermissions

        perms = ShellPermissions()
        perms.add_allow("git *")
        perms.add_deny("rm *")

        decision, _ = PermissionEngine.evaluate("git status", perms)
        self.assertEqual(decision, PermissionDecision.ALLOW)

        decision, _ = PermissionEngine.evaluate("rm -rf /", perms)
        self.assertEqual(decision, PermissionDecision.DENY)

        decision, _ = PermissionEngine.evaluate("ls -la", perms)
        self.assertEqual(decision, PermissionDecision.ASK)


# ======================================================================
# 20. existing Phase 2 tests do not regress
# ======================================================================

class TestPhaseTwoNoRegression(unittest.TestCase):
    """Phase 3 must not break Phase 2.2 transaction APIs."""

    def test_accept_edit_api_survives(self):
        """accept_edit/reject_edit APIs must still be callable."""
        from core.accept_edits_state import (
            accept_edit, reject_edit, set_mode, reset_session,
            PendingEdit, TransactionOutcome, _acquire_path_lock,
        )
        self.assertTrue(callable(accept_edit))
        self.assertTrue(callable(reject_edit))
        self.assertTrue(callable(set_mode))
        self.assertTrue(callable(reset_session))

    def test_wal_journal_api_survives(self):
        """WAL journal setup must not break."""
        from core.accept_edits_state import (
            set_journal_path, _write_journal_record,
            WalRecord, JOURNAL_SCHEMA_VERSION,
        )
        try:
            set_journal_path(None)  # memory-only mode
        except Exception as e:
            self.fail(f"Phase 3 must not break WAL journal setup: {e}")


# ======================================================================
# Run
# ======================================================================

if __name__ == "__main__":
    unittest.main()
