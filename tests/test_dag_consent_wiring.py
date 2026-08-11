import ast
from pathlib import Path
import pytest

def test_call_site_passes():
    src = Path("core/command_dispatcher.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    refactor_fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name == "_cmd_refactor"
    )
    launch_call = None
    for n in ast.walk(refactor_fn):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "launch_nabdos_core"
        ):
            launch_call = n
            break
            
    assert launch_call is not None, "launch_nabdos_core(...) call not found in _cmd_refactor"
    
    kw = {k.arg for k in launch_call.keywords}
    assert "consent_callback" in kw, (
        "core/command_dispatcher.py /refactor must pass consent_callback to launch_nabdos_core"
    )

def test_terminal_node_gate():
    src = Path("core/dag/nodes/terminal.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    execute_fn = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "TerminalNode"
    )
    
    has_fail_closed = False
    for child in ast.walk(execute_fn):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if "fail-closed" in child.value or "Consent denied" in child.value:
                has_fail_closed = True
                break
                
    assert has_fail_closed, "TerminalNode must fail-closed if no consent callback is wired"
