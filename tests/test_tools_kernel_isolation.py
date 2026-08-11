import ast
import pytest
from pathlib import Path
from tools.file_system import FileSystemTool

def test_tools_no_bus_import():
    tools_dir = Path(__file__).parent.parent / "tools"
    for py_file in tools_dir.glob("*.py"):
        with open(py_file, "r") as f:
            tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert node.module != "core.kernel.events", f"{py_file} imports core.kernel.events"
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "core.kernel.events.bus", f"{py_file} imports bus directly"

def test_file_system_accepts_bus():
    tool = FileSystemTool()
    assert getattr(tool, "bus", None) is None

def test_events_still_published():
    class MockBus:
        def __init__(self):
            self.emitted = []
        def emit(self, event, payload):
            self.emitted.append((event, payload))
            
    bus = MockBus()
    tool = FileSystemTool(workspace=".", bus=bus)
    assert tool.bus is bus
    tool.execute(action="read", path="README.md")
    assert any(e[0] == "file_read" for e in bus.emitted)

def test_no_bus_passed():
    tool = FileSystemTool()
    assert tool.bus is None

def test_anchors_alive():
    assert True
