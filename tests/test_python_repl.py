# tests/test_python_repl.py
"""Unit tests for AST-hardened, zero-dependency PythonREPLTool."""

from pathlib import Path
import tempfile
import unittest

from tools.python_repl import PythonREPLTool


class TestPythonREPLTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.tool = PythonREPLTool(workspace=self.workspace)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_normal_execution_with_print(self) -> None:
        code = 'x = 10\ny = 25\nprint(f"Result: {x + y}")'
        res = self.tool.execute(code=code)
        self.assertTrue(res.success, res.stderr)
        self.assertIn("Result: 35", res.stdout)
        self.assertEqual(res.returncode, 0)

    def test_execution_without_print(self) -> None:
        code = 'x = 100 * 5'
        res = self.tool.execute(code=code)
        self.assertTrue(res.success, res.stderr)
        self.assertIn("Did you forget to print()?", res.stdout)

    def test_ast_security_blocks_system_call(self) -> None:
        code = 'import os\nos.system("rm -rf /")'
        res = self.tool.execute(code=code)
        self.assertFalse(res.success)
        self.assertIn("forbidden attribute/method call 'system'", res.stderr)

    def test_ast_security_blocks_subprocess_import(self) -> None:
        code = 'import subprocess\nsubprocess.run(["ls"])'
        res = self.tool.execute(code=code)
        self.assertFalse(res.success)
        self.assertIn("imports forbidden module 'subprocess'", res.stderr)

    def test_ast_security_blocks_from_import(self) -> None:
        code = 'from subprocess import Popen'
        res = self.tool.execute(code=code)
        self.assertFalse(res.success)
        self.assertIn("imports from forbidden module 'subprocess'", res.stderr)

    def test_ast_security_blocks_rmtree_call(self) -> None:
        code = 'import shutil\nshutil.rmtree("/some/path")'
        res = self.tool.execute(code=code)
        self.assertFalse(res.success)
        self.assertIn("forbidden attribute/method call 'rmtree'", res.stderr)

    def test_circuit_breaker_timeout(self) -> None:
        fast_tool = PythonREPLTool(workspace=self.workspace, timeout=0.2)
        code = 'while True:\n    pass'
        res = fast_tool.execute(code=code)
        self.assertFalse(res.success)
        self.assertIn("Script timed out after 0.2 seconds", res.stderr)
        self.assertIn("Possible infinite loop", res.stderr)

    def test_syntax_error_reported_by_execution(self) -> None:
        code = 'def bad_syntax('
        res = self.tool.execute(code=code)
        self.assertFalse(res.success)
        self.assertIn("SyntaxError", res.stderr)


if __name__ == "__main__":
    unittest.main()
