"""Acceptance tests for honest status verbs.

Stage 2 (UI plan): fabricated or alternating verbs like "Choreographing",
"Abracadabraing", "Crafting", "Tuning", "Verifying", "Sculpting" must be
replaced by verbs that reflect what the agent is *actually* doing.
"""

from __future__ import annotations

import pytest

from engine.ui_theme import select_status_verb
from ui.cc_style import next_status_verb


# ── Fabricated verbs that must never appear ────────────────────────────────

_FABRICATED = {
    "Choreographing",
    "Abracadabraing",
    "Crafting",
    "Sculpting",
    "Tuning",
    "Weaving",
    "Conjuring",
    "Contemplating",
    "Drafting",
    "Synthesizing",
}


def test_no_fabricated_verbs_in_select_status_verb():
    """No fabricated verb may ever be returned by select_status_verb."""
    samples = [
        ("plan", "", 0), ("plan", "", 1),
        ("edit", "file_system", 0), ("edit", "file_system", 1),
        ("shell", "execute_shell", 0), ("shell", "execute_shell", 1),
        ("read", "file_system", 0), ("read", "file_system", 1),
        ("init", "", 0), ("init", "", 1),
        ("generating", "", 0),
        ("", "task", 0), ("", "web_search", 0), ("", "rag_search", 0),
        ("", "", 0), ("", "", 1),
    ]
    for stage, tool, idx in samples:
        verb = select_status_verb(stage, tool, idx)
        assert verb not in _FABRICATED, (
            f"Fabricated verb {verb!r} for stage={stage!r} tool={tool!r} idx={idx}"
        )


def test_no_fabricated_verbs_in_next_status_verb():
    """next_status_verb must cycle only honest verbs."""
    for _ in range(20):
        verb = next_status_verb()
        assert verb not in _FABRICATED, f"Fabricated verb {verb!r}"


# ── Verbs reflect actual actions ───────────────────────────────────────────

def test_edit_stage_uses_editing():
    assert select_status_verb("edit", "file_system") == "Editing"
    assert select_status_verb("write", "file_system") == "Editing"


def test_shell_stage_uses_executing():
    assert select_status_verb("shell", "execute_shell") == "Executing"


def test_read_stage_uses_examining():
    assert select_status_verb("read", "file_system") == "Examining"


def test_task_tool_uses_delegating():
    assert select_status_verb("", "task") == "Delegating"
    assert select_status_verb("", "subagent_runner") == "Delegating"


def test_search_tool_uses_searching():
    assert select_status_verb("", "web_search") == "Searching"
    assert select_status_verb("", "rag_search") == "Searching"


def test_generating_uses_writing():
    assert select_status_verb("generating") == "Writing"


def test_unknown_stage_uses_reasoning():
    assert select_status_verb("", "") == "Reasoning"
    assert select_status_verb("", "unknown_tool") == "Reasoning"


# ── Verb is stable across turn_index (no alternation) ──────────────────────

def test_verb_does_not_alternate_with_turn_index():
    """The same stage must produce the same verb regardless of turn parity."""
    assert select_status_verb("edit", "file_system", 0) == select_status_verb("edit", "file_system", 1)
    assert select_status_verb("shell", "execute_shell", 0) == select_status_verb("shell", "execute_shell", 1)
    assert select_status_verb("read", "file_system", 0) == select_status_verb("read", "file_system", 1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
