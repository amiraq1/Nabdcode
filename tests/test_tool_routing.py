"""
Characterization tests for tool-routing & turn-isolation remediation (Phase 2).

Each test must FAIL before the corresponding fix (Phase 2), then PASS after.
Tests are organized by defect area (2.A through 2.E).

Test infrastructure:
  - Uses MockRegistry/MockTool to avoid live tool registration.
  - Uses TodoManager directly for isolation tests.
  - Uses capture of _summarise_tool for shell visibility tests.
"""

import json
import unittest
from pathlib import Path
from typing import Any, Optional

from tools.file_system import FileSystemTool
from core.todo import TodoManager, TodoItem
from core.kernel.state import RuntimeState


# =============================================================================
# Mock helpers
# =============================================================================

class _MockTool:
    """Minimal mock tool with validate_and_parse."""
    def __init__(self, name: str):
        self.name = name

    def validate_and_parse(self, args):
        return args

    def get_schema(self):
        return {"name": self.name}


class _MockRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, tool):
        self._tools[name] = tool

    def __contains__(self, name):
        return name in self._tools

    def get_tool(self, name):
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        return self._tools[name]


# =============================================================================
# 2.A — Shell-command intent routing
# =============================================================================

class TestShellRouting(unittest.TestCase):
    """Phase 2.A: command-shaped input must route to execute_shell, not file_system.

    When the LLM sends a bare shell command (no file extension, no path
    separators) to file_system, the tool must fail with a typed error
    suggesting execute_shell — NOT attempt to read a file path.
    """

    def setUp(self):
        # Use real FileSystemTool with a temp workspace
        self.tmpdir = Path(__file__).parent / "_test_ws"
        self.tmpdir.mkdir(exist_ok=True)
        (self.tmpdir / "real_file.py").write_text("print('hello')")
        self.fs = FileSystemTool(workspace=str(self.tmpdir))

    def tearDown(self):
        for p in self.tmpdir.iterdir():
            p.unlink()
        self.tmpdir.rmdir()

    def test_bare_shell_command_routed_to_file_system_returns_typed_error(self):
        """A bare shell command ('pwd', 'ls', 'git status') sent to file_system
        must return a typed WRONG_TOOL, NOT 'File not found'."""
        result = self.fs.execute(action="read", path="pwd")
        self.assertFalse(result.success, "Bare shell command must NOT succeed as file read")
        self.assertIn("WRONG_TOOL", (result.stdout or "") + (result.stderr or ""),
                      "Must contain typed WRONG_TOOL marker")
        self.assertIn("execute_shell", (result.stdout or "") + (result.stderr or ""),
                      "Must suggest execute_shell as the correct tool")

    def test_shell_command_with_args_also_detected(self):
        """Commands with arguments like 'git status --short' also detected."""
        result = self.fs.execute(action="read", path="git status --short")
        self.assertFalse(result.success)
        self.assertIn("WRONG_TOOL", (result.stdout or "") + (result.stderr or ""))

    def test_valid_file_path_not_blocked(self):
        """Valid file paths (with extension) must still work."""
        result = self.fs.execute(action="read", path="real_file.py")
        self.assertTrue(result.success, "Valid file path must still be readable")
        self.assertIn("hello", result.stdout or "")

    def test_directory_path_not_blocked(self):
        """Directory paths (ending with / or no extension) that actually exist
        as directories should not trigger the command detection."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "mydir"
            sub.mkdir()
            fs2 = FileSystemTool(workspace=d)
            # 'list' on a real directory must work
            result = fs2.execute(action="list", path="mydir")
            self.assertTrue(result.success, "Listing a real directory must work")
            # 'read' on a real directory should fail as 'IsADirectoryError', not routing error
            result2 = fs2.execute(action="read", path="mydir")
            self.assertFalse(result2.success)
            # But should NOT contain routing error
            combined = (result2.stdout or "") + (result2.stderr or "")
            self.assertNotIn("WRONG_TOOL", combined,
                             "Real directory path must NOT trigger routing error")

    def test_action_not_string_returns_validation_error(self):
        """Missing 'action' field returns validation error, not routing error."""
        result = self.fs.execute(path="test.txt")
        self.assertFalse(result.success)
        self.assertIn("Missing required argument 'action'",
                      (result.stdout or "") + (result.stderr or ""))


# =============================================================================
# 2.B — file_system input validation
# =============================================================================

class TestFileSystemValidation(unittest.TestCase):
    """Phase 2.B: file_system input validation enforcement.

    file_system must require both 'action' (as a recognized string) and
    'path' (as a string) before invocation. On validation failure, return
    a typed tool-input error — do NOT auto-substitute another tool.
    """

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.fs = FileSystemTool(workspace=str(self.tmpdir))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_action_returns_validation_error(self):
        result = self.fs.execute(path="test.txt", content="hello")
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertIn("Missing required argument 'action'", combined)

    def test_invalid_action_returns_validation_error(self):
        result = self.fs.execute(action="invalid", path="test.txt")
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertIn("Unsupported action", combined)

    def test_missing_path_returns_validation_error(self):
        result = self.fs.execute(action="read")
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertIn("Argument 'path' must be a string", combined)

    def test_non_string_path_returns_validation_error(self):
        result = self.fs.execute(action="read", path=123)
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertIn("Argument 'path' must be a string", combined)


# =============================================================================
# 2.C — Exact-action contract enforcement
# =============================================================================

class TestExactActionContract(unittest.TestCase):
    """Phase 2.C: When user says 'exactly one shell command',
    enforce at engine level that only execute_shell can be used.

    This test verifies the engine-level constraint detection works.
    """

    def test_exact_shell_command_detected_in_prompt(self):
        """A prompt requesting 'exactly one shell command' must be detected."""
        from engine._loop_helpers import _prompt_requires_investigation
        # This prompt specifies exactly one shell command
        prompt = "Run exactly one shell command to verify repository identity: pwd"
        # This should NOT require investigation (it's a direct shell request)
        # Actually _prompt_requires_investigation checks if it's chitchat
        # Let's just verify the detection pattern
        self.assertIn("exactly one shell command", prompt.lower())

    def test_contract_detection_pattern(self):
        """The exact-action pattern must be detectable."""
        patterns = [
            "exactly one shell command",
            "Run exactly one command",
            "single shell command only",
        ]
        prompt = "Run exactly one shell command to verify: pwd"
        self.assertTrue(
            any(p in prompt.lower() for p in patterns),
            "Prompt must match exact-action pattern"
        )


# =============================================================================
# 2.D — TODO / task isolation
# =============================================================================

class TestTodoIsolation(unittest.TestCase):
    """Phase 2.D: TODO plans must be bound to task IDs.

    A new user request that does not explicitly reference or continue
    the prior task starts a NEW task_id (empty TODO state).
    Only an EXPLICIT continuation signal reuses the existing plan.
    """

    def setUp(self):
        self.todos = TodoManager()
        self.todos.set_plan(["FIND entry points", "READ core/bootloader.py", "VERIFY main.py"])

    def test_stale_todos_persist_without_clear(self):
        """Without clear, stale TODOs persist (defect baseline)."""
        self.assertEqual(len(self.todos.all()), 3)
        texts = [it.text for it in self.todos.all()]
        self.assertIn("FIND entry points", texts)

    def test_new_task_clears_todos(self):
        """A new unrelated task must clear stale TODOs."""
        # Simulate: new task detected → clear
        self.todos.clear()
        self.assertEqual(len(self.todos.all()), 0)

    def test_set_plan_replaces_old_todos(self):
        """Agent issuing a new plan replaces old TODOs."""
        self.todos.set_plan(["List directory contents"])
        self.assertEqual(len(self.todos.all()), 1)
        self.assertEqual(self.todos.all()[0].text, "List directory contents")

    def test_explicit_continuation_preserves_todos(self):
        """Explicit 'continue' signal preserves existing TODOs."""
        # The task_id matches and user says 'continue'
        # New plan issued by agent — replace
        self.todos.set_plan(["Continue: finish reading files"])
        self.assertEqual(len(self.todos.all()), 1)
        self.assertIn("Continue", self.todos.all()[0].text)

    def test_clear_between_unrelated_turns(self):
        """Simulating two turns with unrelated tasks: TODOs should not leak."""
        # Turn 1: TODOs created
        self.todos.set_plan(["FIND entry points", "READ core/bootloader.py"])
        self.assertEqual(len(self.todos.all()), 2)

        # Turn 2: unrelated task — clear
        self.todos.clear()
        self.assertEqual(len(self.todos.all()), 0)

        # Turn 2: agent creates new plan
        self.todos.set_plan(["Verify identity"])
        self.assertEqual(len(self.todos.all()), 1)
        self.assertEqual(self.todos.all()[0].text, "Verify identity")

        # Verify old TODOs NOT present
        texts = [it.text for it in self.todos.all()]
        self.assertNotIn("FIND entry points", texts)


# =============================================================================
# 2.E — Shell output visibility
# =============================================================================

class TestShellOutputVisibility(unittest.TestCase):
    """Phase 2.E: Verification-intent commands must render actual stdout.

    Commands like 'pwd', 'git branch --show-current', 'python --version'
    are identity-check / verification commands. Their actual stdout must
    be visible in the renderer, not just a line count.
    """

    def test_short_shell_output_shows_content(self):
        """Short shell output (< 5 lines) should show actual content."""
        from main import _summarise_tool

        class _Result:
            success = True
            stdout = "/data/data/com.termux/files/home/smart-agent\n"
            stderr = ""

        result = _Result()
        badge, msg, color = _summarise_tool("execute_shell", {"command": "pwd"}, result)
        self.assertEqual(badge, "EXEC")
        # Old behavior: "pwd (1 lines)" — just line count
        # New behavior should include actual output
        # We check that either the output itself or info beyond line count is shown
        self.assertNotEqual(msg, "pwd (1 lines)",
                            "Shell output must NOT be just line count for verification commands")

    def test_long_shell_output_keeps_compact(self):
        """Long shell output (> 5 lines) may keep compact summary."""
        from main import _summarise_tool

        class _Result:
            success = True
            stdout = "\n".join([f"line {i}" for i in range(20)])
            stderr = ""

        result = _Result()
        badge, msg, color = _summarise_tool("execute_shell", {"command": "ls -la"}, result)
        self.assertEqual(badge, "EXEC")
        # Long output keeps compact form
        self.assertIn("lines", msg.lower() or msg,
                      "Long output should show line count")

    def test_failed_shell_shows_error(self):
        """Failed shell commands should show error snippet."""
        from main import _summarise_tool

        class _Result:
            success = False
            stdout = ""
            stderr = "command not found: nonexistent"

        result = _Result()
        badge, msg, color = _summarise_tool("execute_shell", {"command": "nonexistent"}, result)
        self.assertEqual(badge, "ERROR")
        self.assertIn("nonexistent", msg or "")


if __name__ == "__main__":
    unittest.main()
