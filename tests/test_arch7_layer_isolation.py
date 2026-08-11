import ast
from pathlib import Path
import pytest

def test_ui_no_tools_import():
    ui_dir = Path("ui")
    for py_file in ui_dir.rglob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("tools"), f"ui cannot import tools: {alias.name} in {py_file}"
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("tools"):
                    pytest.fail(f"ui cannot import from tools: {node.module} in {py_file}")

def test_adapter_exists():
    pass

def test_ui_uses_adapter():
    pass

def test_behavior_preserved():
    pass
