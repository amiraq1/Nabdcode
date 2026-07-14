"""Automated verification suite for hardened production secure toolchain.

Covers SecureWorkspaceReader, SecureGitInspector, and SecureTestRunner
ensuring path traversal protection, symlink escape protection, binary/oversized block,
command allowlisting, flag injection prevention, and timeout handling.
"""

import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.secure_tools import (
    SecureGitInspector,
    SecureTestRunner,
    SecureWorkspaceReader,
    SecureSemanticMemoryTool,
    SecureShellTool,
)


class TestSecureWorkspaceReader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = pathlib.Path(self.temp_dir)
        self.reader = SecureWorkspaceReader(
            workspace_root=str(self.workspace),
            max_file_size=1000,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_path_traversal_blocked(self):
        result = self.reader.forward("../../etc/passwd")
        self.assertIn("Security Violation", result)

    def test_symlink_escape_blocked(self):
        outside_file = pathlib.Path(self.temp_dir) / ".." / "secret_outside.txt"
        symlink_path = self.workspace / "escape_link.txt"
        try:
            symlink_path.symlink_to(outside_file)
            result = self.reader.forward("escape_link.txt")
            self.assertIn("Security Violation", result)
        except (OSError, NotImplementedError):
            pass

    def test_missing_file(self):
        result = self.reader.forward("nonexistent.txt")
        self.assertIn("not found", result)

    def test_directory_blocked(self):
        sub_dir = self.workspace / "sub"
        sub_dir.mkdir()
        result = self.reader.forward("sub")
        self.assertIn("is a directory", result)

    def test_binary_file_blocked(self):
        bin_file = self.workspace / "data.bin"
        bin_file.write_bytes(b"\x00\x01\x02\x03BINARY")
        result = self.reader.forward("data.bin")
        self.assertIn("Cannot read binary file", result)

    def test_huge_file_blocked(self):
        huge_file = self.workspace / "huge.txt"
        huge_file.write_text("A" * 2000, encoding="utf-8")
        result = self.reader.forward("huge.txt")
        self.assertIn("exceeds maximum allowed size", result)

    def test_successful_read_sanitized(self):
        clean_file = self.workspace / "hello.txt"
        clean_file.write_text("Hello \x1b[31mRed\x1b[0m World!", encoding="utf-8")
        result = self.reader.forward("hello.txt")
        self.assertEqual(result, "Hello Red World!")

    def test_read_with_path_keyword(self):
        clean_file = self.workspace / "hello_path.txt"
        clean_file.write_text("Tested with path keyword", encoding="utf-8")
        result = self.reader.forward(path="hello_path.txt")
        self.assertEqual(result, "Tested with path keyword")

    def test_read_with_kwargs(self):
        clean_file = self.workspace / "hello_kw.txt"
        clean_file.write_text("Tested with arbitrary kwarg", encoding="utf-8")
        result = self.reader.forward(filename="hello_kw.txt", extra="foo")
        self.assertEqual(result, "Tested with arbitrary kwarg")


class TestSecureGitInspector(unittest.TestCase):
    def setUp(self):
        self.inspector = SecureGitInspector(repo_path=".")

    def test_invalid_command_blocked(self):
        result = self.inspector.forward("commit")
        self.assertIn("Security Violation: Invalid action", result)

    def test_injected_flags_blocked(self):
        result = self.inspector.forward("--exec=rm -rf")
        self.assertIn("Security Violation: Invalid action", result)

    def test_non_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            inspector = SecureGitInspector(repo_path=tmp_dir)
            result = inspector.forward("status")
            self.assertIn("not a Git repository", result)

    def test_valid_status_execution(self):
        result = self.inspector.forward("status")
        self.assertFalse(result.startswith("Security Violation"))

    @patch("subprocess.run")
    def test_timeout_handling(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=10)
        result = self.inspector.forward("status")
        self.assertIn("timed out", result)


class TestSecureTestRunner(unittest.TestCase):
    def setUp(self):
        self.runner = SecureTestRunner(repo_path=".")

    def test_invalid_target_blocked(self):
        result = self.runner.forward("../../etc/passwd")
        self.assertIn("Security Violation: Target", result)

    def test_blocked_arguments(self):
        result = self.runner.forward("-k test_foo")
        self.assertIn("Security Violation", result)

    def test_successful_execution(self):
        result = self.runner.forward("unit")
        self.assertFalse(result.startswith("Security Violation"))

    @patch("subprocess.run")
    def test_timeout_handling(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python3"], timeout=30)
        result = self.runner.forward("unit")
        self.assertIn("timed out", result)


class TestSecureSemanticMemoryTool(unittest.TestCase):
    def setUp(self):
        from core.memory import SemanticMemoryPipeline
        self.temp_dir = tempfile.mkdtemp()
        self.store_path = pathlib.Path(self.temp_dir) / "tool_memory.json"
        pipeline = SemanticMemoryPipeline(store_path=str(self.store_path))
        self.tool = SecureSemanticMemoryTool(memory_pipeline=pipeline)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_store_and_search_lesson(self):
        res_store = self.tool.forward(action="store", text="Always validate inputs before subprocess execution")
        self.assertIn("Successfully stored lesson", res_store)

        res_search = self.tool.forward(action="search", text="validate inputs subprocess")
        self.assertIn("Retrieved Semantic Memory Lessons:", res_search)
        self.assertIn("validate inputs", res_search)

    def test_invalid_action_blocked(self):
        res = self.tool.forward(action="delete_all", text="test")
        self.assertIn("Security Violation", res)


class TestSecureShellTool(unittest.TestCase):
    def setUp(self):
        self.tool = SecureShellTool()

    def test_forward_with_positional_string(self):
        res = self.tool.forward("echo test_string")
        self.assertIn("test_string", res)

    def test_forward_with_positional_list(self):
        res = self.tool.forward(["echo test_list"])
        self.assertIn("test_list", res)

    def test_forward_with_keyword_list(self):
        res = self.tool.forward(command=["echo test_kw_list"])
        self.assertIn("test_kw_list", res)

    def test_forward_with_dict_mapping(self):
        res = self.tool.forward({"command": "echo test_dict"})
        self.assertIn("test_dict", res)


if __name__ == "__main__":
    unittest.main()
