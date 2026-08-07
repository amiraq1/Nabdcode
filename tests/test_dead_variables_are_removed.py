"""tests/test_dead_variables_are_removed.py — V8 + V9 guard.

V8: _SESSION_PERMS and _SESSION_PERMS_STATE must be removed.
V9: echo_user_input function and _last_echoed_input variable must be removed.

These are dead artifacts that survived refactorings:

_SESSION_PERMS (V8):
    A ShellPermissions() singleton that is never consumed by any production
    path. Only used as an alias in one characterization test.

_SESSION_PERMS_STATE (V8):
    A None sentinel kept for backward-compat with characterization tests.
    The test it supports (TestNoModuleLevelFallbackState) must be updated
    to not require this import.

echo_user_input (V9):
    A function that writes the user's input to stdout. PromptSession already
    echoes input, so this is a no-op that only adds noise.

_last_echoed_input (V9):
    A module-level string that tracks the last echoed input. Dead since
    echo_user_input became a no-op.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path("ui/repl_termux.py")


# ── V8 guards ──────────────────────────────────────────────────────────────────

def test_session_perms_is_removed() -> None:
    """V8: _SESSION_PERMS must be removed — dead ShellPermissions singleton."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_SESSION_PERMS":
                    raise AssertionError(
                        f"_SESSION_PERMS still assigned at line {node.lineno}.\n"
                        "It is a dead variable (not consumed in production). Remove it."
                    )


def test_session_perms_state_is_removed() -> None:
    """V8: _SESSION_PERMS_STATE must be removed — dead sentinel."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_SESSION_PERMS_STATE":
                    raise AssertionError(
                        f"_SESSION_PERMS_STATE still assigned at line {node.lineno}.\n"
                        "It is a dead sentinel. Remove it and update "
                        "test_phase3_runtime_state.py::TestNoModuleLevelFallbackState."
                    )


# ── V9 guards ──────────────────────────────────────────────────────────────────

def test_echo_user_input_is_removed() -> None:
    """V9: echo_user_input function must be removed — it's a no-op."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "echo_user_input":
            raise AssertionError(
                f"echo_user_input still defined at line {node.lineno}.\n"
                "PromptSession already echoes input. This function is a no-op. Remove it."
            )


def test_last_echoed_input_is_removed() -> None:
    """V9: _last_echoed_input must be removed — dead variable."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_last_echoed_input":
                    raise AssertionError(
                        f"_last_echoed_input still assigned at line {node.lineno}.\n"
                        "It is a dead variable. Remove it along with echo_user_input."
                    )
