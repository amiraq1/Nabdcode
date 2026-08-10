"""C1 Guard: Ensure main.py keeps AgentStatusBar listening on the bus.

UI-CC-7: the bar is wired (listens) but NOT started (no live box rendering).
The inline compact line (status_compact_line) is the visual feedback instead.
"""

from __future__ import annotations

import ast
import pathlib
import pytest

def test_renderer_wires_to_status_bar():
    """C1: AgentStatusBar must be imported and wired (not started) in main.py."""
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

    # 2. Verify status_bar.wire() is called in wire_events
    has_wire = False
    has_start = False
    has_stop = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "status_bar":
                if node.func.attr == "wire":
                    has_wire = True
                elif node.func.attr == "start":
                    has_start = True
                elif node.func.attr == "stop":
                    has_stop = True

    assert has_wire, "status_bar.wire() must be called (bar listens on the bus)"
    assert not has_start, "status_bar.start() must NOT be called (UI-CC-7: no live box)"
    assert not has_stop, "status_bar.stop() must NOT be called (UI-CC-7: no live box)"
