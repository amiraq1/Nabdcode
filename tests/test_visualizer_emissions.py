"""Regression tests pinning the three TerminalVisualizer event emissions.

These guard against accidental removal of the bus.emit calls that drive the
visualizer's on-screen panels:

  - ``agent_handoff``      emitted by MultiAgentOrchestrator on role transitions
  - ``tool_auth_violation`` emitted by ExecutionLoop when is_safe_command rejects
  - ``show_final_answer``   emitted by ExecutionLoop on clean final_answer completion

Each test subscribes to the real engine event bus and asserts the exact
payload fields, so a refactor that drops or renames an emit fails loudly.
"""

import unittest
from unittest.mock import MagicMock

from core.kernel.events import bus


class MagicMockWorker:
    """Minimal stand-in for CoderAgent/VerifierAgent that records no tools.

    Only the ``code`` / ``evaluate`` callables invoked by coordinate() matter;
    everything else is stubbed so no real CodeAgent/LLM is constructed.
    """

    def __init__(self, code=None, evaluate=None):
        if code is not None:
            self.code = code
        if evaluate is not None:
            self.evaluate = evaluate

    def underlying(self):  # pragma: no cover - not exercised by the test
        return None


class TestAgentHandoffEmission(unittest.TestCase):
    def test_orchestrator_emits_handoffs_on_role_transitions(self):
        """Orchestrator -> Coder / Coder -> Auditor / Auditor -> Coder must
        each emit an agent_handoff with correct from/to roles and a payload."""
        from core.multi_agent_orchestrator import OrchestratorAgent

        orch = OrchestratorAgent.__new__(OrchestratorAgent)
        # Avoid real model/network/worker construction.
        orch.coder = MagicMockWorker(
            code=lambda brief: "def solution():\n    return 42"
        )
        orch.verifier = MagicMockWorker(
            evaluate=lambda goal, payload: {"passed": True, "reasons": [], "fix_hint": ""}
        )
        orch.scratchpad = {
            "goal": "", "history": "", "payload": "",
            "attempts": 0, "rejections": [],
        }
        # Stub the side-effect helpers the coordinate() loop touches.
        orch._build_history_context = lambda: ""
        orch._persist_lesson_if_any = lambda *a, **k: None
        # Stub the local sandbox smoke test so the clean payload reaches the
        # Verifier branch (where the Coder -> Auditor handoff is emitted).
        import core.multi_agent_orchestrator as _mod
        _mod.SafeExecutionSandbox.smoke_test_code = staticmethod(
            lambda code: {"passed": True, "error": ""}
        )

        handoffs = []

        def _capture(payload):
            handoffs.append(dict(payload))
        unsub = bus.subscribe("agent_handoff", _capture)
        try:
            result = orch.coordinate("write a function that returns 42", max_retries=1)
        finally:
            unsub()

        self.assertEqual(result["status"], "verified")
        # ORCHESTRATOR->CODER and CODER->AUDITOR must fire; the orchestrator
        # short-circuits on first pass, so AUDITOR->CODER (reject) must not.
        self.assertGreaterEqual(len(handoffs), 2)
        roles = [(h["from_role"], h["to_role"]) for h in handoffs]
        self.assertIn(("ORCHESTRATOR", "CODER"), roles)
        self.assertIn(("CODER", "AUDITOR"), roles)
        # Every handoff carries a non-empty payload.
        for h in handoffs:
            self.assertIn("payload", h)
            self.assertTrue(h["payload"])


class TestToolAuthViolationEmission(unittest.TestCase):
    def setUp(self):
        try:
            from engine.tool_registry import registry
            from tools.shell import ShellTool
            registry.register(ShellTool())
        except ValueError:
            pass

    def test_unsafe_shell_command_emits_auth_violation(self):
        """When is_safe_command rejects an execute_shell command, the loop must
        emit tool_auth_violation with role/tool/error."""
        from engine.loop import ExecutionLoop
        from engine.state import RuntimeState

        state = RuntimeState(session_id="test-auth-violation")
        # Return a final_answer-free tool call that requests a forbidden shell
        # command so the security gate trips (no real LLM needed beyond step 1).
        mock_llm = MagicMock(
            return_value='{"tool": "execute_shell", "args": {"command": "rm -rf /"}}'
        )
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

        violations = []

        def _capture(payload):
            violations.append(dict(payload))
        unsub = bus.subscribe("tool_auth_violation", _capture)
        try:
            loop.run("delete everything")
        finally:
            unsub()

        self.assertEqual(len(violations), 1)
        v = violations[0]
        self.assertEqual(v["role"], "ORCHESTRATOR")
        self.assertEqual(v["tool"], "execute_shell")
        self.assertTrue(v["error"])


class TestShowFinalAnswerEmission(unittest.TestCase):
    def test_final_answer_emits_show_final_answer(self):
        """A clean final_answer termination must emit show_final_answer with the
        answer text, in addition to loop_completed."""
        from engine.loop import ExecutionLoop
        from engine.state import RuntimeState

        state = RuntimeState(session_id="test-show-final-answer")
        mock_llm = MagicMock(
            return_value='{"tool": "final_answer", "args": {"answer": "Hello! How can I help today?"}}'
        )
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

        finals = []

        def _capture(payload):
            finals.append(dict(payload))
        unsub = bus.subscribe("show_final_answer", _capture)
        try:
            loop.run("hi")
        finally:
            unsub()

        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["output"], "Hello! How can I help today?")
        self.assertEqual(state.status, "COMPLETED")


if __name__ == "__main__":
    unittest.main()
