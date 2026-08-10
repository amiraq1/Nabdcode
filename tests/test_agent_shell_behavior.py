"""tests/test_agent_shell_behavior.py — Am+9 UX-2: Shell Output Handling.

Red-guard tests verifying that the system prompt instructs the agent to
summarize shell output directly instead of reading files individually.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


MAIN_FILE = Path(__file__).resolve().parent.parent / "main.py"


def _read_base_inst() -> str:
    """Extract the base_inst string from main.py source."""
    source = MAIN_FILE.read_text(encoding="utf-8")
    # Find the base_inst assignment block
    match = re.search(
        r'base_inst\s*=\s*\((.*?)\)\s*\n',
        source,
        re.DOTALL,
    )
    assert match, "base_inst not found in main.py"
    return match.group(1)


# ── ع1: system_prompt_contains_shell_summary_instruction ───────────────────────

def test_system_prompt_contains_shell_summary_instruction() -> None:
    """Section C must instruct the agent to summarize shell output directly."""
    base_inst = _read_base_inst()
    assert "C) AFTER SHELL EXECUTION" in base_inst, "Section C not found in system prompt"
    assert "Summarize the Shell output directly" in base_inst, (
        "Shell summary instruction not found"
    )


# ── ع2: system_prompt_forbids_unnecessary_file_reads ────────────────────────────

def test_system_prompt_forbids_unnecessary_file_reads() -> None:
    """System prompt must forbid file_system.read after execute_shell."""
    base_inst = _read_base_inst()
    assert "DO NOT call file_system.read" in base_inst, (
        "File read prohibition not found in system prompt"
    )
    assert "NEVER call file_system.read after execute_shell" in base_inst, (
        "Explicit file read prohibition not found"
    )


# ── ع3: system_prompt_has_example ───────────────────────────────────────────────

def test_system_prompt_has_example() -> None:
    """System prompt must include a concrete example of shell summarization."""
    base_inst = _read_base_inst()
    assert "Example:" in base_inst, "Example not found in system prompt"
    assert "directory contains" in base_inst.lower() or "files" in base_inst.lower(), (
        "Example does not demonstrate shell output summarization"
    )
