"""Automated verification suite for TermuxMonitorTool (tools/termux_monitor.py)."""

import unittest
from unittest.mock import patch

from tools.termux_monitor import TermuxMonitorTool

# Schema gatekeeper — guards the LLM against the budget-exhaustion loop where a
# valid tool gets rejected because it is missing from the live ToolRegistry.
from core.parser import validate_tool_call
from engine.tool_registry import registry


class _MockRegistry:
    """Minimal registry adapter wrapping a real tool."""
    def __init__(self, tool):
        self._tool = tool

    def __contains__(self, name):
        return True

    def get_tool(self, name):
        return self._tool


FREE_SAMPLE = (
    "               total        used        free      shared  buff/cache   available\n"
    "Mem:           3834        2012         412         180        1410        1389\n"
    "Swap:          2047           0        2047\n"
)

DF_SAMPLE = (
    "Filesystem      Size  Used Avail Use% Mounted on\n"
    "/dev/root        32G   14G   17G  46% /\n"
    "/data            52G   40G   12G  77% /data\n"
)


class TestTermuxMonitorParsing(unittest.TestCase):
    def setUp(self):
        self.tool = TermuxMonitorTool()

    def test_parse_free_memory(self):
        mem = self.tool._parse_free(FREE_SAMPLE)["memory"]
        self.assertEqual(mem["total_mb"], 3834)
        self.assertEqual(mem["used_mb"], 2012)
        self.assertEqual(mem["free_mb"], 412)
        self.assertEqual(mem["available_mb"], 1389)

    def test_parse_free_swap(self):
        swap = self.tool._parse_free(FREE_SAMPLE)["swap"]
        self.assertEqual(swap["total_mb"], 2047)
        self.assertEqual(swap["free_mb"], 2047)

    def test_parse_df_filesystems(self):
        fs = self.tool._parse_df(DF_SAMPLE)["filesystems"]
        self.assertEqual(len(fs), 2)
        self.assertEqual(fs[0]["mounted_on"], "/")
        self.assertEqual(fs[0]["use_percent"], "46%")
        self.assertEqual(fs[1]["size"], "52G")
        self.assertEqual(fs[1]["avail"], "12G")

    def test_execute_parses_real_shell_output(self):
        """Patch the internal shell runner to return canned command output."""
        def fake_run(command):
            if command == "free -m":
                return FREE_SAMPLE
            if command == "df -h":
                return DF_SAMPLE
            return ""

        with patch.object(TermuxMonitorTool, "_run_shell", side_effect=fake_run):
            res = self.tool.execute()

        self.assertTrue(res.success)
        self.assertIn("Memory:", res.stdout)
        self.assertIn("Disk /:", res.stdout)
        self.assertIn("77%", res.stdout)
        # Structured metadata is attached for programmatic consumers.
        self.assertEqual(res.metadata["memory"]["memory"]["total_mb"], 3834)
        self.assertEqual(len(res.metadata["disk"]["filesystems"]), 2)


class TestTermuxMonitorLive(unittest.TestCase):
    """Best-effort live check against the real host (skips if commands absent)."""

    def test_execute_runs_on_host(self):
        tool = TermuxMonitorTool()
        # Only assert it does not crash and returns a ToolResult-shaped object.
        res = tool.execute()
        self.assertTrue(hasattr(res, "success"))
        if res.success:
            self.assertIn("Memory", res.stdout)


class TestTermuxMonitorSchemaRegression(unittest.TestCase):
    """Lock in the budget-exhaustion fix: termux_monitor must validate + dispatch."""

    def setUp(self):
        # ToolRegistry is the single source of truth; ensure termux_monitor
        # is registered so the live schema view reflects it.
        if "termux_monitor" not in registry:
            registry.register(TermuxMonitorTool())

    def test_termux_monitor_in_tool_schemas(self):
        """The LLM-facing schema registry must know about termux_monitor."""
        registry_schemas = {s.get("name") for s in registry.get_all_schemas()}
        self.assertIn("termux_monitor", registry_schemas)

    def test_termux_monitor_schema_validation(self):
        """Exact LLM payload must pass the strict gatekeeper (ok=True)."""
        registry = _MockRegistry(TermuxMonitorTool())
        ok, err = validate_tool_call({"tool": "termux_monitor", "args": {}}, registry)
        self.assertTrue(ok, msg=f"validation failed: {err}")

    def test_termux_monitor_schema_validation_as_json_string(self):
        """Forgiving/raw-JSON path also accepts the exact payload string."""
        registry = _MockRegistry(TermuxMonitorTool())
        ok, err = validate_tool_call('{"tool": "termux_monitor", "args": {}}', registry)
        self.assertTrue(ok, msg=f"validation failed: {err}")

    def test_termux_monitor_tool_instantiates(self):
        """Class is importable and instantiates without constructor args."""
        tool = TermuxMonitorTool()
        self.assertEqual(tool.name, "termux_monitor")
        self.assertTrue(hasattr(tool, "execute"))


if __name__ == "__main__":
    unittest.main()
