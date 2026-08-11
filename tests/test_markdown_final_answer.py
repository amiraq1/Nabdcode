import ast
from pathlib import Path
import pytest
from rich.markdown import Markdown
from rich.text import Text

def test_renderer_exists():
    try:
        from ui.cc_style import render_final_answer
        res = render_final_answer("**bold text**")
        assert isinstance(res, Markdown)
    except ImportError:
        pytest.fail("render_final_answer not found in ui.cc_style")

def test_fallback_safe():
    from ui.cc_style import render_final_answer
    
    # We monkeypatch Markdown to raise an exception
    import rich.markdown
    original_markdown = rich.markdown.Markdown
    
    class BrokenMarkdown:
        def __init__(self, *args, **kwargs):
            raise ValueError("Intentional Markdown failure")
    
    rich.markdown.Markdown = BrokenMarkdown
    try:
        res = render_final_answer("broken")
        assert isinstance(res, Text)
    finally:
        rich.markdown.Markdown = original_markdown

def test_repl_uses_renderer():
    p = Path("ui/repl_termux.py")
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    uses_renderer = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "on_final_answer":
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "render_final_answer":
                    uses_renderer = True
                    break
    
    assert uses_renderer, "ui/repl_termux.py must use render_final_answer"

def test_oneshot_stays_plain():
    p = Path("main.py")
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    
    uses_renderer = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_one_shot_query":
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and getattr(child.func, "id", "") == "render_final_answer":
                    uses_renderer = True
                    break
    
    assert not uses_renderer, "main.py must NOT use render_final_answer in _handle_one_shot_query"
