"""Tests for /fix slash command — function extraction + AST parsing.

The /fix command in main.py uses AST to extract a function from a file,
displays it with line numbers, and runs UI tests. This test validates
the core logic: file parsing, function finding, and line-number extraction.

Does NOT test the full REPL interaction (input/output/process spawning) —
that requires end-to-end integration testing with tmux.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ── Test fixture: a mini temporary file with known functions ────────────

_SAMPLE_CODE = """
from __future__ import annotations


def hello(name: str) -> str:
    return f"Hello, {name}!"


class MyClass:
    def method_one(self, x: int) -> int:
        return x * 2

    async def method_two(self, y: str) -> str:
        return y.upper()


def _strip_tool_call_lines(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('{'):
            continue
        result.append(line)
    return chr(10).join(result).strip()
"""


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    """Create a temporary Python file with sample functions."""
    p = tmp_path / "test_module.py"
    p.write_text(_SAMPLE_CODE, encoding="utf-8")
    return p


def _extract_function(filepath: Path, func_name: str) -> tuple[list[str], int, int] | None:
    """Core logic from /fix: extract function lines from a file by name.

    Returns (func_lines, start_line, end_line) or None if not found.
    Mirrors the AST-walking code in main.py._process_slash_command.
    """
    content = filepath.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(filepath))

    found = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            found = node
            break

    if found is None:
        return None

    lines = content.splitlines()
    start = found.lineno - 1
    end = getattr(found, "end_lineno", len(lines))
    func_lines = lines[start:end]
    return (func_lines, found.lineno, end)


class TestFixCommandCore:
    """Test the core /fix logic: file parsing + AST function extraction."""

    def test_extract_top_level_function(self, sample_file):
        """Extract a top-level function by name."""
        result = _extract_function(sample_file, "hello")
        assert result is not None, "Function 'hello' should be found"
        func_lines, start, end = result
        assert len(func_lines) >= 1
        assert func_lines[0].strip() == 'def hello(name: str) -> str:'
        # hello() is at line 5 in _SAMPLE_CODE (after imports + blank lines)
        assert start == 5

    def test_extract_private_function(self, sample_file):
        """Extract a private/dunder function."""
        result = _extract_function(sample_file, "_strip_tool_call_lines")
        assert result is not None, "Function '_strip_tool_call_lines' should be found"
        func_lines, start, end = result
        assert len(func_lines) >= 3
        assert "_strip_tool_call_lines" in func_lines[0]

    def test_extract_class_method(self, sample_file):
        """Extract a regular class method."""
        result = _extract_function(sample_file, "method_one")
        assert result is not None, "Method 'method_one' should be found"
        func_lines, start, end = result
        assert func_lines[0].strip() == 'def method_one(self, x: int) -> int:'

    def test_extract_async_method(self, sample_file):
        """Extract an async class method."""
        result = _extract_function(sample_file, "method_two")
        assert result is not None, "Method 'method_two' should be found"
        func_lines, start, end = result
        assert func_lines[0].strip() == 'async def method_two(self, y: str) -> str:'

    def test_function_not_found_returns_none(self, sample_file):
        """Requesting a non-existent function returns None."""
        result = _extract_function(sample_file, "nonexistent_function")
        assert result is None

    def test_empty_file_returns_none(self, tmp_path):
        """An empty file has no functions to extract."""
        p = tmp_path / "empty.py"
        p.write_text("", encoding="utf-8")
        result = _extract_function(p, "anything")
        assert result is None

    def test_syntax_error_file_raises(self, tmp_path):
        """A file with syntax errors should propagate the SyntaxError."""
        p = tmp_path / "broken.py"
        p.write_text("def broken(:", encoding="utf-8")
        with pytest.raises(SyntaxError):
            _extract_function(p, "broken")


class TestFixCommandIntegration:
    """Lightweight integration: verify _process_slash_command runs without crashing.

    These test the slash-command dispatch with a mock state/ctx to confirm
    the /fix branch is reachable and doesn't blow up on valid input.
    """

    def test_slash_fix_dispatches(self):
        """_process_slash_command returns True for /fix, consuming the input."""
        from main import _process_slash_command

        class MockState:
            def clear_context(self):
                pass
            def set_messages(self, msgs):
                pass
            def get_messages(self):
                return []

        class MockCtx:
            class evidence_log:
                @staticmethod
                def clear():
                    pass
            class todo_manager:
                @staticmethod
                def clear():
                    pass
            logger = type("Logger", (), {"info": lambda *a: None, "warning": lambda *a: None})()

        state = MockState()
        ctx = MockCtx()
        # /fix with a non-existent file should be handled gracefully (not crash)
        result = _process_slash_command("/fix nonexistent.py -> foo", state, ctx, "sys prompt")
        assert result is True, "/fix should consume the input even when file not found"
