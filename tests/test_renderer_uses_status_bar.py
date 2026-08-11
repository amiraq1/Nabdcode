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
    # ARCH-5: wire() moved to ui/event_wiring.py
    # ARCH-5b: status_bar instance remains in main.py (lazy-resolution)
    main_src = pathlib.Path('main.py').read_text(encoding='utf-8')
    assert "AgentStatusBar" in main_src, "AgentStatusBar must be imported in main.py"
    
    wiring_src = pathlib.Path('ui/event_wiring.py').read_text(encoding='utf-8')
    assert "status_bar.wire()" in wiring_src, "status_bar.wire() must be called in event_wiring"
    assert "status_bar.start(" not in wiring_src, "C1: start() must NOT be called on protected bar"

    tree = ast.parse(wiring_src)
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
