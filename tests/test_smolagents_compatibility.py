"""Unit and regression tests for smolagents compatibility engine (`CodeAgent`, data-driven dispatch, and ReAct loop)."""

import unittest
from unittest.mock import MagicMock
from smolagents import CodeAgent, Tool, ManagedAgent, LiteLLMModel


class MockTool(Tool):
    def __init__(self, name: str, return_value: str = "mock result"):
        super().__init__()
        self.name = name
        self.description = f"Mock tool {name}"
        self.inputs = {"arg": {"type": "string", "description": "test arg"}}
        self._return_value = return_value
        self.forward_mock = MagicMock(return_value=return_value)

    def forward(self, *args, **kwargs):
        return self.forward_mock(*args, **kwargs)


class TestSmolagentsCodeAgent(unittest.TestCase):
    def test_fast_path_data_driven_dispatch_exact_matches(self):
        """Ensure specific targeted commands hit data-driven fast-paths cleanly without ReAct loop overhead."""
        mem_tool = MockTool("secure_semantic_memory", return_value="Stored lesson")
        test_tool = MockTool("secure_test_runner", return_value="All 5 tests passed")
        git_tool = MockTool("secure_git_inspector", return_value="M main.py")
        reader_tool = MockTool("secure_workspace_reader", return_value="print('hello')")

        agent = CodeAgent(tools=[mem_tool, test_tool, git_tool, reader_tool])

        # Semantic memory fast-path
        res_mem = agent.run("Please remember this lesson about architecture")
        self.assertEqual(res_mem, "Stored lesson")
        mem_tool.forward_mock.assert_called_once()

        # Test runner fast-path
        res_test = agent.run("run pytest on tests/test_loop.py")
        self.assertEqual(res_test, "All 5 tests passed")
        test_tool.forward_mock.assert_called_once_with(test_target="tests/test_loop.py")

        # Git inspector fast-path
        res_git = agent.run("check git status right now")
        self.assertEqual(res_git, "M main.py")
        git_tool.forward_mock.assert_called_once_with(action="status")

        # Workspace reader fast-path
        res_read = agent.run("read file main.py")
        self.assertEqual(res_read, "print('hello')")
        reader_tool.forward_mock.assert_called_once_with(file_path="main.py")

    def test_fast_path_avoids_false_positives(self):
        """Ensure general questions containing words like 'latest' or 'status code' are NOT hijacked by fast-paths."""
        test_tool = MockTool("secure_test_runner")
        git_tool = MockTool("secure_git_inspector")
        mock_model = MagicMock()
        mock_model.chat = MagicMock(return_value='```json\n{"tool": "final_answer", "args": {"answer": "It is an HTTP error"}}\n```')

        agent = CodeAgent(tools=[test_tool, git_tool], model=mock_model)

        # "latest" should NOT trigger test_tool
        res1 = agent.run("What is the latest API pattern?")
        self.assertEqual(res1, "It is an HTTP error")
        test_tool.forward_mock.assert_not_called()

        # "status code 404" should NOT trigger git_tool
        res2 = agent.run("Explain what status code 404 means.")
        self.assertEqual(res2, "It is an HTTP error")
        git_tool.forward_mock.assert_not_called()

    def test_managed_agent_delegation(self):
        """Ensure CodeAgent delegates to targeted sub-agents when requested."""
        sub_agent_mock = MagicMock()
        sub_agent_mock.run = MagicMock(return_value="Sub-agent solved task")
        managed = ManagedAgent(agent=sub_agent_mock, name="coder", description="Writes code")

        agent = CodeAgent(managed_agents=[managed])
        res = agent.run("Ask coder to write a binary search tree")
        self.assertEqual(res, "Sub-agent solved task")
        sub_agent_mock.run.assert_called_once()

    def test_react_loop_tool_execution_and_final_answer(self):
        """Ensure ReAct loop executes tools and terminates on final_answer cleanly without errors."""
        shell_tool = MockTool("secure_shell", return_value="file1.py\nfile2.py")
        mock_model = MagicMock()
        # Step 1: call secure_shell; Step 2: return final_answer
        mock_model.chat = MagicMock(side_effect=[
            'Thought: I need to list files\n```json\n{"tool": "secure_shell", "args": {"command": "ls"}}\n```',
            '```json\n{"tool": "final_answer", "args": {"answer": "Found 2 files"}}\n```'
        ])

        agent = CodeAgent(tools=[shell_tool], model=mock_model, max_steps=5)
        res = agent.run("List files in repo")
        self.assertEqual(res, "Found 2 files")
        shell_tool.forward_mock.assert_called_once_with(command="ls")
        self.assertEqual(mock_model.chat.call_count, 2)


if __name__ == "__main__":
    unittest.main()
