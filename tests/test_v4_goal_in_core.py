"""
V4.1 Architecture Guard: handle_goal_command must live in core/commands/goal.py

The "UI is a mirror" principle: state mutations (_active_goal, etc.)
belong in core/, not in the UI layer.

This guard ensures:
1. core/commands/goal.py is importable with handle_goal_command
2. It accepts (text, agent) and returns the GoalSpec or None
3. ui/repl_termux.py's _handle_goal_command delegates to core
"""
import ast
import pathlib
import importlib


def test_core_commands_goal_module_exists():
    """core/commands/goal.py must exist and export handle_goal_command."""
    try:
        mod = importlib.import_module("core.commands.goal")
    except ImportError as e:
        raise AssertionError(
            f"core/commands/goal.py not found or not importable: {e}\n"
            "V4.1 fix: create core/commands/goal.py with handle_goal_command()"
        ) from e
    assert hasattr(mod, "handle_goal_command"), (
        "core.commands.goal must export handle_goal_command(text, agent) → GoalSpec|None"
    )


def test_ui_repl_delegates_goal_to_core():
    """AST guard: _handle_goal_command in repl_termux must import from core.commands.goal."""
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)

    # Look for 'from core.commands.goal import' or 'import core.commands.goal'
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "core.commands.goal" in node.module:
                return  # Found delegation import
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "core.commands.goal" in alias.name:
                    return

    raise AssertionError(
        "ui/repl_termux.py does not import from core.commands.goal — "
        "goal logic must be delegated to core/, not embedded in UI. "
        "V4.1 fix: extract _handle_goal_command to core/commands/goal.py"
    )
