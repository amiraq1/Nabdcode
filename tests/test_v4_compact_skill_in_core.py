"""
V4.2 Architecture Guard: handle_compact_command must live in core/commands/compact.py
V4.3 Architecture Guard: handle_skill_command must live in core/commands/skill.py

V-BURY-1 (Am, 2026-08-09): the dead UI wrappers ``_handle_compact_command``
and ``_handle_skill_command`` in ui/repl_termux.py were buried with the
orphaned async REPL (run_repl). The delegation contract now resolves
entirely in core — the UI layer defines no wrappers at all.
"""
import ast
import importlib
import pathlib


# ── V4.2 — /compact ──────────────────────────────────────────────────────────

def test_core_commands_compact_module_exists():
    """core/commands/compact.py must exist and export handle_compact_command."""
    try:
        mod = importlib.import_module("core.commands.compact")
    except ImportError as e:
        raise AssertionError(
            f"core/commands/compact.py not found or not importable: {e}\n"
            "V4.2 fix: create core/commands/compact.py with handle_compact_command()"
        ) from e
    assert hasattr(mod, "handle_compact_command"), (
        "core.commands.compact must export handle_compact_command(agent) → dict"
    )


def test_ui_repl_no_longer_wraps_compact_command():
    """AST guard: _handle_compact_command must NOT be defined in ui/repl_termux.py.

    V-BURY-1: the dead UI wrapper was buried with run_repl. Compact logic
    lives ONLY in core/commands/compact.py.
    """
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)
    wrappers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_handle_compact_command"
    ]
    assert not wrappers, (
        "_handle_compact_command must NOT be defined in ui/repl_termux.py — "
        "it was buried with run_repl (V-BURY-1). Compact logic lives ONLY in "
        "core/commands/compact.py. "
        "V4.2 fix: delegate _handle_compact_command to core/commands/compact.py"
    )


def test_compact_command_returns_dict():
    """handle_compact_command(None) must return a dict with expected keys."""
    from core.commands.compact import handle_compact_command
    result = handle_compact_command(None)
    assert isinstance(result, dict), "handle_compact_command must return dict"
    assert "success" in result
    assert "old_tokens" in result
    assert "new_tokens" in result
    assert "saved" in result


# ── V4.3 — /skill ────────────────────────────────────────────────────────────

def test_core_commands_skill_module_exists():
    """core/commands/skill.py must exist and export handle_skill_command."""
    try:
        mod = importlib.import_module("core.commands.skill")
    except ImportError as e:
        raise AssertionError(
            f"core/commands/skill.py not found or not importable: {e}\n"
            "V4.3 fix: create core/commands/skill.py with handle_skill_command()"
        ) from e
    assert hasattr(mod, "handle_skill_command"), (
        "core.commands.skill must export handle_skill_command(text, agent) → dict|None"
    )


def test_ui_repl_no_longer_wraps_skill_command():
    """AST guard: _handle_skill_command must NOT be defined in ui/repl_termux.py.

    V-BURY-1: the dead UI wrapper was buried with run_repl. Skill logic
    lives ONLY in core/commands/skill.py.
    """
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)
    wrappers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_handle_skill_command"
    ]
    assert not wrappers, (
        "_handle_skill_command must NOT be defined in ui/repl_termux.py — "
        "it was buried with run_repl (V-BURY-1). Skill logic lives ONLY in "
        "core/commands/skill.py. "
        "V4.3 fix: delegate _handle_skill_command to core/commands/skill.py"
    )


def test_skill_command_returns_none_for_non_skill_input():
    """handle_skill_command with non-/skill text must return None."""
    from core.commands.skill import handle_skill_command
    result = handle_skill_command("hello world", None)
    assert result is None, (
        f"handle_skill_command('hello world') should return None, got {result!r}"
    )


def test_skill_command_returns_dict_for_skill_input():
    """handle_skill_command with /skill text must return a dict (even if skill not found)."""
    from core.commands.skill import handle_skill_command
    result = handle_skill_command("/skill nonexistent_skill_xyz", None)
    assert isinstance(result, dict), (
        f"handle_skill_command('/skill ...') should return dict, got {result!r}"
    )
    assert result.get("consumed") is True
    assert "success" in result
