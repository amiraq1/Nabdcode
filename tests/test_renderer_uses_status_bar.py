"""C1 Guard: Ensure main.py uses AgentStatusBar in the production path."""

from __future__ import annotations

import ast
import pathlib
import pytest

def test_renderer_wires_to_status_bar():
    """C1: Renderer must wire to AgentStatusBar in production path (main.py)."""
    source = pathlib.Path('main.py').read_text(encoding='utf-8')
    tree = ast.parse(source)

    # 1. Verify AgentStatusBar is imported
    has_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "ui.widgets.status_bar":
                if any(alias.name == "AgentStatusBar" for alias in node.names):
                    has_import = True
                    break
    assert has_import, "AgentStatusBar must be imported in main.py"

    # 2. Verify status_bar.start() in _on_llm_started
    has_start = False
    has_stop = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name == "_on_llm_started":
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute):
                        if isinstance(stmt.func.value, ast.Name) and stmt.func.value.id == "status_bar":
                            if stmt.func.attr == "start":
                                has_start = True
            elif node.name == "_on_llm_completed":
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute):
                        if isinstance(stmt.func.value, ast.Name) and stmt.func.value.id == "status_bar":
                            if stmt.func.attr == "stop":
                                has_stop = True

    assert has_start, "status_bar.start() must be called in _on_llm_started"
    assert has_stop, "status_bar.stop() must be called in _on_llm_completed"
