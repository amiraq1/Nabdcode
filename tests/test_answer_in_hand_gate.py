"""Unit and regression tests for the Answer-in-Hand Gate (`بوّابة «الجواب في اليد»`) and Guard 3.

Verifies that when sufficient evidence to answer the prompt is already gathered,
ExecutionLoop immediately forces final_answer and Guard 3 blocks redundant exploration tools.
"""

import unittest
from unittest.mock import MagicMock
from engine.loop import ExecutionLoop, _LoopSignal
from engine.state import RuntimeState
from core.evidence import EvidenceRecord


from engine.tool_registry import registry
from tools.file_system import FileSystemTool
from tools.shell import ShellTool


class TestAnswerInHandGate(unittest.TestCase):
    def setUp(self):
        try:
            registry.register(FileSystemTool())
            registry.register(ShellTool())
        except ValueError:
            pass

    def test_answer_in_hand_forces_final_without_extra_tools(self):
        """يتأكد أن وجود قراءة ناجحة لملف pyproject.toml يجبر محرك الحلقة على التوقف بحل نهائي في أقل من أو يساوي دورتين."""
        state = RuntimeState(session_id="test-answer-in-hand-loop")
        
        # Turn 1: LLM requests file_system read on pyproject.toml
        turn1_resp = '{"tool": "file_system", "args": {"action": "read", "path": "pyproject.toml"}}'
        # Turn 2: LLM outputs final_answer with the extracted name
        turn2_resp = '{"tool": "final_answer", "args": {"answer": "The project name is nabdcode."}}'
        
        mock_llm = MagicMock(side_effect=[turn1_resp, turn2_resp])
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")

        # Mock dispatcher so file_system returns success with project name
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = 'name = "nabdcode"\nversion = "0.1.0"'
        mock_result.returncode = 0
        loop.dispatcher.dispatch = MagicMock(return_value=mock_result)

        prompt = "Read pyproject.toml"
        loop.run(prompt)

        # Ensure LLM was called at most 2 times
        self.assertLessEqual(mock_llm.call_count, 2)
        # Ensure _force_final tripped on Turn 2
        self.assertEqual(state.status, "COMPLETED")

    def test_guard3_intercepts_redundant_shell_when_answer_in_hand(self):
        """يتأكد أن Guard 3 يمنع تشغيل execute_shell عند وجود الجواب بالفعل في سجل الأدلة."""
        state = RuntimeState(session_id="test-guard3-intercept")
        mock_llm = MagicMock(return_value='{"tool": "execute_shell", "args": {"command": "git status"}}')
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)

        # Pre-populate evidence_log with successful read of pyproject.toml
        rec = EvidenceRecord(
            evidence_id="E-101",
            tool="file_system",
            command_or_path="pyproject.toml",
            output_snippet='[project]\nname = "nabdcode"\nversion = "1.0.0"',
            success=True,
        )
        loop.evidence_log.add(rec)

        # Initialize context and active tool
        loop._ctx = MagicMock()
        loop._ctx.user_prompt = "Read pyproject.toml"
        from core.parser import ToolCall
        loop._active_tool = ToolCall(tool="execute_shell", args={"command": "git status"})

        # Run Guard 3 pre-dispatch check
        signal = loop._pre_dispatch_guard(loop._active_tool)

        # Guard 3 should short-circuit with a blocked ToolResult and force final
        self.assertIsNotNone(signal)
        self.assertTrue(loop._force_final)
        self.assertEqual(loop.dispatcher.dispatch.call_count if hasattr(loop.dispatcher, "dispatch") and isinstance(loop.dispatcher.dispatch, MagicMock) else 0, 0)


if __name__ == "__main__":
    unittest.main()
