"""
V4.2 Architecture Guard: handle_compact_command must live in core/commands/compact.py
V4.3 Architecture Guard: handle_skill_command must live in core/commands/skill.py
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


def test_ui_repl_delegates_compact_to_core():
    """AST guard: _handle_compact_command in repl_termux must import from core.commands.compact."""
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "core.commands.compact" in node.module:
                return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "core.commands.compact" in alias.name:
                    return
    raise AssertionError(
        "ui/repl_termux.py does not import from core.commands.compact — "
        "compact logic must be delegated to core/. "
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


def test_ui_repl_delegates_skill_to_core():
    """AST guard: _handle_skill_command in repl_termux must import from core.commands.skill."""
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "core.commands.skill" in node.module:
                return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "core.commands.skill" in alias.name:
                    return
    raise AssertionError(
        "ui/repl_termux.py does not import from core.commands.skill — "
        "skill logic must be delegated to core/. "
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
