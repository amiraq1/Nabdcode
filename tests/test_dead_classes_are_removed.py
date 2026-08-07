"""tests/test_dead_classes_are_removed.py — V7 guard.

Verifies that class REPL has been removed from ui/repl_termux.py.
class REPL is a dead class: it is only used by one test
(test_phase_goal_12_polish.py::test_repl_goal_panel_rendering) and not by
any production code path.

After removal, test_phase_goal_12_polish.py::test_repl_goal_panel_rendering
must be updated to use handle_goal_command (from core.commands.goal) directly.
"""

from __future__ import annotations

import ast
import pathlib


def test_repl_class_is_dead() -> None:
    """V7: class REPL must be removed — it is not used in production."""
    tree = ast.parse(pathlib.Path("ui/repl_termux.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "REPL":
            raise AssertionError(
                f"class REPL still exists at line {node.lineno}.\n"
                "It is a dead class (not used in production).\n"
                "Remove it and update test_phase_goal_12_polish.py."
            )
