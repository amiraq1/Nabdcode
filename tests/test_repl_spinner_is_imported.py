"""REGRESSION — repl_termux used `Spinner` without importing it.

HEAD committed `ui/repl_termux.py:1620` calls `Spinner("dots", ...)` while
the module only imported `SPINNERS`. Every tool_started raised NameError,
swallowed by the `except Exception` in `on_tool_started`, so tools ran
without a spinner. The AST check below proves the runtime bug without
executing the REPL.
"""

import ast
import pathlib

_REPL = (
    pathlib.Path(__file__).resolve().parents[1] / "ui" / "repl_termux.py"
)


def test_repl_imports_rich_spinner():
    """A live REPL surface must import the Spinner it constructs."""
    tree = ast.parse(_REPL.read_text(encoding="utf-8"))
    imports_rich_spinner = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "rich.spinner":
            names = {alias.name for alias in node.names}
            if "Spinner" in names:
                imports_rich_spinner = True
    assert imports_rich_spinner, (
        "ui/repl_termux.py constructs rich Spinner at runtime but never "
        "imports it — NameError is swallowed by on_tool_started's except."
    )
