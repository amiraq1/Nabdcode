"""tests/test_phase2_pending_edits.py — Characterization tests for Pending Edits architecture."""

import pytest
import ast
from pathlib import Path
from core.accept_edits_state import PendingEdit

def test_production_pending_edit_function_exists():
    """Verify that _process_pending_edits exists in ui/repl_termux.py."""
    repl_path = Path("ui/repl_termux.py")
    assert repl_path.exists()
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert "_process_pending_edits" in functions

def test_repl_has_direct_file_write_path_legacy():
    """Characterization test: REPL must NOT write files directly."""
    repl_path = Path("ui/repl_termux.py")
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    
    process_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_process_pending_edits")
    calls = [n for n in ast.walk(process_func) if isinstance(n, ast.Call)]
    
    # Check if write_text is called
    has_write_text = False
    for call in calls:
        if isinstance(call.func, ast.Attribute) and call.func.attr == "write_text":
            has_write_text = True
            break
            
    assert has_write_text is False

def test_repl_calls_drain_pending_directly_legacy():
    """Characterization test: REPL must NOT call drain_pending directly."""
    repl_path = Path("ui/repl_termux.py")
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    
    process_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_process_pending_edits")
    calls = [n for n in ast.walk(process_func) if isinstance(n, ast.Call)]
    
    has_drain = False
    for call in calls:
        if isinstance(call.func, ast.Attribute) and call.func.attr == "drain_pending":
            has_drain = True
            break
            
    assert has_drain is False

def test_repl_delegates_accept_to_canonical_api():
    """Target architecture: REPL must delegate accept to canonical API."""
    repl_path = Path("ui/repl_termux.py")
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    
    process_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_process_pending_edits")
    calls = [n for n in ast.walk(process_func) if isinstance(n, ast.Call)]
    
    has_accept = False
    for call in calls:
        if isinstance(call.func, ast.Attribute) and call.func.attr == "accept_edit":
            has_accept = True
            break
            
    assert has_accept is True

def test_repl_has_no_direct_file_write_path():
    """Target architecture: REPL must not call write_text."""
    repl_path = Path("ui/repl_termux.py")
    content = repl_path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    
    process_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_process_pending_edits")
    calls = [n for n in ast.walk(process_func) if isinstance(n, ast.Call)]
    
    has_write_text = False
    for call in calls:
        if isinstance(call.func, ast.Attribute) and call.func.attr == "write_text":
            has_write_text = True
            break
            
    assert has_write_text is False
