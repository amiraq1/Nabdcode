"""
V4.1 Architecture Guard: handle_goal_command must live in core/commands/goal.py

The "UI is a mirror" principle: state mutations (_active_goal, etc.)
belong in core/, not in the UI layer.

V-BURY-1 (Am, 2026-08-09): the dead UI wrapper ``_handle_goal_command`` in
ui/repl_termux.py was buried with the orphaned async REPL (run_repl). The
delegation contract now resolves entirely in core: core/commands/goal.py is
the ONLY home of handle_goal_command, and the UI layer no longer defines a
goal wrapper at all.
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


def test_ui_repl_no_longer_wraps_goal_command():
    """AST guard: _handle_goal_command must NOT be defined in ui/repl_termux.py.

    V-BURY-1: the dead UI wrapper was buried with run_repl. Goal logic lives
    ONLY in core/commands/goal.py — the UI layer must not resurrect a wrapper.
    """
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)
    wrappers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_handle_goal_command"
    ]
    assert not wrappers, (
        "_handle_goal_command must NOT be defined in ui/repl_termux.py — "
        "it was buried with run_repl (V-BURY-1). Goal logic lives ONLY in "
        "core/commands/goal.py. "
        "V4.1 fix: extract _handle_goal_command to core/commands/goal.py"
    )
