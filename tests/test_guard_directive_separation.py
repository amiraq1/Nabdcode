"""Regression test for Phase 0 root fix: guard directives must NOT leak into evidence_log.

Verifies the channel-separation contract:
  (a) PERSISTENCE — a pre-dispatch guard interception is never recorded in
      evidence_log / output_snippet (evidence = real tool outputs only).
  (b) DELIVERY — the directive reaches the model as a [CONTROL] message
      (role "user"), never disguised as a "[TOOL RESULT: ...]" artifact.

This locks in the fix for the SYSTEM DIRECTIVE leak that previously entered
evidence_log.output_snippet and was re-narrated by the model as raw JSON.
"""

import unittest
from unittest.mock import MagicMock

from engine.loop import ExecutionLoop
from engine.state import RuntimeState
from core.evidence import EvidenceRecord

from engine.tool_registry import registry
from tools.file_system import FileSystemTool
from tools.shell import ShellTool
from core.parser import ToolCall


class TestGuardDirectiveChannelSeparation(unittest.TestCase):
    def setUp(self):
        try:
            registry.register(FileSystemTool())
            registry.register(ShellTool())
        except ValueError:
            pass

    def _build_loop_with_answer_in_hand(self):
        state = RuntimeState(session_id="test-guard-leak-separation")
        loop = ExecutionLoop(llm_provider=MagicMock(), state=state)
        # Pre-populate evidence with a successful targeted read.
        rec = EvidenceRecord(
            evidence_id="E-201",
            tool="file_system",
            command_or_path="pyproject.toml",
            output_snippet='[project]\nname = "nabdcode"\nversion = "1.0.0"',
            success=True,
        )
        loop.evidence_log.add(rec)
        loop._ctx = MagicMock()
        loop._ctx.user_prompt = "Read pyproject.toml"
        loop._ctx.consecutive_no_tool_rounds = 0
        return loop, state

    def test_guard_directive_not_in_evidence_log(self):
        """Guard 3 interception must not write its [SYSTEM DIRECTIVE] to evidence_log."""
        loop, _ = self._build_loop_with_answer_in_hand()
        before = len(loop.evidence_log.get_records())

        tc = ToolCall(tool="execute_shell", args={"command": "git status"})
        loop._active_tool = tc
        signal = loop._pre_dispatch_guard(tc)

        self.assertIsNotNone(signal)
        self.assertTrue(loop._force_final)

        after = len(loop.evidence_log.get_records())
        self.assertEqual(
            after, before,
            "Pre-dispatch guard must NOT record anything to evidence_log",
        )

        # And crucially the existing records must contain no directive text.
        for rec in loop.evidence_log.get_records():
            self.assertNotIn(
                "SYSTEM DIRECTIVE", rec.output_snippet,
                "Directive text leaked into evidence_log.output_snippet",
            )

    def test_guard_directive_delivered_as_control_not_tool_result(self):
        """The injected message must be role 'user' tagged [CONTROL], not a [TOOL RESULT] system artifact."""
        loop, state = self._build_loop_with_answer_in_hand()
        state.append_message = MagicMock(wraps=state.append_message)

        tc = ToolCall(tool="execute_shell", args={"command": "git status"})
        loop._active_tool = tc
        # Invoke the live choke-point's injection path directly.
        pre = loop._pre_dispatch_guard(tc)
        self.assertIsNotNone(pre)
        loop._inject_guard_directive(pre)

        injected = [m for m in state.get_messages() if m.get("role") == "user" and m.get("content", "").startswith("[CONTROL]")]
        self.assertTrue(injected, "Expected a [CONTROL] user-role message for the guard directive")

        tool_result = [m for m in state.get_messages() if "[TOOL RESULT:" in m.get("content", "")]
        self.assertFalse(tool_result, "Guard directive must NOT be delivered as a [TOOL RESULT] artifact")

        # Evidence log still untouched after a guard interception.
        for rec in loop.evidence_log.get_records():
            self.assertNotIn("SYSTEM DIRECTIVE", rec.output_snippet)


if __name__ == "__main__":
    unittest.main()
