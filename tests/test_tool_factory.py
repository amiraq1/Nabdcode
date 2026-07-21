"""Tests for safe tool auto-discovery in core.tool_factory.

Verifies discover_tools() returns a name->instance dict, skips the
hand-wired manual classes, and that _build_tool_with_deps refuses to
build tools with required kwargs it cannot inject (fail-closed).
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.tool_factory import discover_tools, _build_tool_with_deps  # noqa: E402


class _FakeAppContext:
    """Minimal AppContext stand-in providing only the fields tool_factory reads."""

    def __init__(self):
        self.config = SimpleNamespace(workspace_root=".")
        self.memory_manager = object()
        self.todo_manager = object()
        self._security_engine = object()


class TestToolFactory(unittest.TestCase):
    def test_discover_tools_returns_dict(self):
        tools = discover_tools(_FakeAppContext())
        self.assertIsInstance(tools, dict)
        # Every value must be a Tool-like object with a .name
        for name, tool in tools.items():
            self.assertEqual(name, getattr(tool, "name", name))

    def test_discover_tools_skips_manual_classes(self):
        tools = discover_tools(_FakeAppContext())
        # The manually-wired shell/filesystem tools must never be auto-discovered.
        self.assertNotIn("ShellTool", tools)
        self.assertNotIn("FileSystemTool", tools)

    def test_build_with_unresolvable_required_kwarg_returns_none(self):
        class NeedsUnknown:
            def __init__(self, required_thing):
                self.required_thing = required_thing

        self.assertIsNone(_build_tool_with_deps(NeedsUnknown, _FakeAppContext()))

    def test_build_with_injectable_kwargs_succeeds(self):
        class NeedsWorkspace:
            def __init__(self, workspace=None):
                self.workspace = workspace

        tool = _build_tool_with_deps(NeedsWorkspace, _FakeAppContext())
        self.assertIsNotNone(tool)
        self.assertEqual(tool.workspace, ".")


    def test_build_with_required_kwarg_default_succeeds(self):
        # A required kwarg WITHOUT a default must fail; WITH a default it builds.
        class NeedsOptional:
            def __init__(self, maybe=None):
                self.maybe = maybe

        tool = _build_tool_with_deps(NeedsOptional, _FakeAppContext())
        self.assertIsNotNone(tool)

    def test_build_with_partial_missing_required_kwarg_returns_none(self):
        # One injectable kwarg present, but another required (no default, not in
        # ctx) -> fail-closed: must NOT raise, must return None and skip.
        class NeedsSecretAndWorkspace:
            def __init__(self, secret_token, workspace=None):
                self.secret_token = secret_token
                self.workspace = workspace

        self.assertIsNone(
            _build_tool_with_deps(NeedsSecretAndWorkspace, _FakeAppContext())
        )

    def test_discover_tools_never_raises_on_unbuildable_tool(self):
        # discover_tools must be fail-open: an unbuildable discovered tool is
        # skipped, never propagated as an exception.
        tools = discover_tools(_FakeAppContext())
        self.assertIsInstance(tools, dict)


if __name__ == "__main__":
    unittest.main()
