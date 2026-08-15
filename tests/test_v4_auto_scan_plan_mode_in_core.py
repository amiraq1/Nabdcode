"""
V4.4 Architecture Guard: maybe_auto_scan must live in core/commands/auto_scan.py
V4.5 Architecture Guard: PLAN_MODE_INSTRUCTION and inject_plan_mode must live in
      core/commands/plan_mode.py
"""
import ast
import importlib
import pathlib


# ── V4.4 — auto_scan ─────────────────────────────────────────────────────────

def test_core_commands_auto_scan_module_exists():
    """core/commands/auto_scan.py must exist and export maybe_auto_scan."""
    try:
        mod = importlib.import_module("core.commands.auto_scan")
    except ImportError as e:
        raise AssertionError(
            f"core/commands/auto_scan.py not found: {e}\n"
            "V4.4 fix: create core/commands/auto_scan.py with maybe_auto_scan()"
        ) from e
    assert hasattr(mod, "maybe_auto_scan"), (
        "core.commands.auto_scan must export maybe_auto_scan(text, agent) → dict"
    )


def test_auto_scan_returns_dict_structure():
    """maybe_auto_scan must return a dict with triggered/success/entry_count/error."""
    from core.commands.auto_scan import maybe_auto_scan
    # Non-scan input → not triggered
    result = maybe_auto_scan("hello world", None)
    assert isinstance(result, dict), "maybe_auto_scan must return dict"
    assert "triggered" in result
    assert "success" in result
    assert "entry_count" in result
    assert "workspace_root" in result  # Stage 4: explicit workspace root
    assert result["triggered"] is False


# ── V4.5 — plan_mode ─────────────────────────────────────────────────────────

def test_core_commands_plan_mode_module_exists():
    """core/commands/plan_mode.py must exist and export PLAN_MODE_INSTRUCTION + inject/restore."""
    try:
        mod = importlib.import_module("core.commands.plan_mode")
    except ImportError as e:
        raise AssertionError(
            f"core/commands/plan_mode.py not found: {e}\n"
            "V4.5 fix: create core/commands/plan_mode.py with PLAN_MODE_INSTRUCTION"
        ) from e
    assert hasattr(mod, "PLAN_MODE_INSTRUCTION"), (
        "core.commands.plan_mode must export PLAN_MODE_INSTRUCTION (str)"
    )
    assert hasattr(mod, "inject_plan_mode"), (
        "core.commands.plan_mode must export inject_plan_mode(messages) → str|None"
    )
    assert hasattr(mod, "restore_system_prompt"), (
        "core.commands.plan_mode must export restore_system_prompt(messages, snapshot)"
    )


def test_plan_mode_instruction_is_single_source():
    """PLAN_MODE_INSTRUCTION in core/ must match the one used in repl_termux."""
    from core.commands.plan_mode import PLAN_MODE_INSTRUCTION as core_instr
    src = pathlib.Path("ui/repl_termux.py").read_text()
    # repl_termux must import PLAN_MODE_INSTRUCTION from core
    assert "core.commands.plan_mode" in src, (
        "ui/repl_termux.py must import PLAN_MODE_INSTRUCTION from core.commands.plan_mode. "
        "V4.5 fix: replace local PLAN_MODE_INSTRUCTION with import from core."
    )


def test_inject_plan_mode_mutates_messages():
    """inject_plan_mode must prepend PLAN_MODE_INSTRUCTION to system message."""
    from core.commands.plan_mode import inject_plan_mode, PLAN_MODE_INSTRUCTION
    msgs = [{"role": "system", "content": "original"}]
    snapshot = inject_plan_mode(msgs)
    assert snapshot == "original"
    assert msgs[0]["content"].startswith(PLAN_MODE_INSTRUCTION)
    assert "original" in msgs[0]["content"]


def test_restore_system_prompt_restores():
    """restore_system_prompt must restore original content."""
    from core.commands.plan_mode import inject_plan_mode, restore_system_prompt
    msgs = [{"role": "system", "content": "original"}]
    snapshot = inject_plan_mode(msgs)
    restore_system_prompt(msgs, snapshot)
    assert msgs[0]["content"] == "original"
