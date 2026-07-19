"""tests/test_graphify_tool.py — Unit verification suite for GraphifyTool."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from tools.graphify_tool import GraphifyTool


class TestGraphifyTool(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.tool = GraphifyTool(workspace_dir=self.test_dir)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_missing_graphify_out_error(self):
        # Without graphify-out directory, query/explain/path should ask to update first
        res = self.tool.forward(action="query", target="authentication")
        self.assertIn("Error: graphify-out/ directory not found", res)

    def test_invalid_actions_and_missing_targets(self):
        # Create dummy graphify-out directory
        os.makedirs(os.path.join(self.test_dir, "graphify-out"), exist_ok=True)

        # Invalid action
        inv = self.tool.forward(action="destroy")
        self.assertIn("Error: Invalid action.", inv)

        # Query missing target
        query_missing = self.tool.forward(action="query")
        self.assertIn("Error: Action 'query' requires a 'target'", query_missing)

        # Path missing target_b
        path_missing = self.tool.forward(action="path", target="nodeA")
        self.assertIn("Error: Action 'path' requires both 'target' (Node A) and 'target_b'", path_missing)

    @patch("subprocess.run")
    def test_mock_subprocess_run_success(self, mock_run):
        # Create dummy graphify-out directory
        os.makedirs(os.path.join(self.test_dir, "graphify-out"), exist_ok=True)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Found node: core/kernel/security.py -> SecurityEngine"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        res = self.tool.forward(action="query", target="security")
        self.assertEqual(res, "Found node: core/kernel/security.py -> SecurityEngine")
        mock_run.assert_called_once_with(
            ["graphify", "query", "security"],
            cwd=self.test_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_graphify_cli_not_found(self, mock_run):
        os.makedirs(os.path.join(self.test_dir, "graphify-out"), exist_ok=True)
        res = self.tool.forward(action="query", target="auth")
        self.assertIn("Execution Error: 'graphify' command not found", res)

    @patch("subprocess.run")
    def test_execute_returns_tool_result(self, mock_run):
        os.makedirs(os.path.join(self.test_dir, "graphify-out"), exist_ok=True)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Explanation of taste engine."
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = self.tool.execute(action="explain", target="TasteEngine")
        self.assertTrue(result.success)
        self.assertEqual(result.stdout, "Explanation of taste engine.")
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
