# tests/test_phase_context_compaction.py
from engine.state import RuntimeState, GoalSpec
from core.context_compactor import ContextCompactor, _ToolInteraction


def test_compactor_triggers_at_8kb():
    """Compaction triggers when context exceeds 8KB"""
    compactor = ContextCompactor()

    # Generate large messages (>8KB)
    messages = [
        {"role": "system", "content": "x" * 5000},
        {"role": "user", "content": "y" * 5000},
    ]
    assert compactor.should_compact(messages) is True


def test_compaction_preserves_anchors():
    """System and user messages are always preserved"""
    compactor = ContextCompactor()

    messages = [
        {"role": "system", "content": "SYSTEM_PROMPT"},
        {"role": "user", "content": "ORIGINAL_TASK"},
        {"role": "assistant", "content": "old response 1"},
        {"role": "user", "content": "old response 2"},
    ]
    state = RuntimeState(session_id="test")
    compacted = compactor.compact(messages, state)

    # Anchors preserved
    assert compacted[0]["content"] == "SYSTEM_PROMPT"
    assert compacted[1]["content"] == "ORIGINAL_TASK"
    assert len(compacted) >= 2


def test_compaction_preserves_goal():
    """Active goal is preserved in compaction"""
    compactor = ContextCompactor()

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    state = RuntimeState(session_id="test", active_goal=GoalSpec("test", "criteria"))
    compacted = compactor.compact(messages, state)

    # Goal block present
    assert any("<active_goal" in m.get("content", "") for m in compacted)


def test_compaction_sums_up_old_tools():
    """Old tool interactions are summarized"""
    compactor = ContextCompactor()
    compactor.config.tool_window = 2

    # Create mock interactions
    interactions = [
        _ToolInteraction(1, "read", True, "file1", "ev1", "Read README", False),
        _ToolInteraction(2, "grep", True, "pattern", "ev2", "Found 3 matches", False),
        _ToolInteraction(3, "execute_shell", False, "ls", "ev3", "Permission denied", False),
    ]

    state = RuntimeState(session_id="test", tool_interactions=interactions)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "response with tools"},
    ]
    compacted = compactor.compact(messages, state)

    # Should have past_steps_summary with old tools
    summary_found = any("past_steps_summary" in m.get("content", "") for m in compacted)
    assert summary_found


def test_compaction_preserves_critical_evidence():
    """Critical evidence is included in compaction"""
    from core.evidence import EvidenceStore, EvidenceLog, EvidenceRecord
    compactor = ContextCompactor()

    store = EvidenceStore()
    store.add({"tool": "read", "args": {}}, "critical output 1", True)
    store.add({"tool": "grep", "args": {}}, "normal output", True)

    # Mark one as critical
    store.flag_critical("ev_0")

    evidence_log = EvidenceLog()
    evidence_log.store = store

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    state = RuntimeState(session_id="test")
    compacted = compactor.compact(messages, state, evidence_log)

    # Critical evidence present
    assert any("critical_evidence" in m.get("content", "") for m in compacted)


def test_compaction_respects_tool_window():
    """Last N tools are kept full, older ones summarized"""
    compactor = ContextCompactor()
    compactor.config.tool_window = 2

    interactions = [
        _ToolInteraction(1, "tool1", True, "", "ev1", "old 1", False),
        _ToolInteraction(2, "tool2", True, "", "ev2", "old 2", False),
        _ToolInteraction(3, "tool3", True, "", "ev3", "recent 1", False),
        _ToolInteraction(4, "tool4", True, "", "ev4", "recent 2", False),
    ]

    state = RuntimeState(session_id="test", tool_interactions=interactions)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    compacted = compactor.compact(messages, state)

    # Should contain recent_tools block
    recent_found = any("recent_tools" in m.get("content", "") for m in compacted)
    assert recent_found

    # Should contain past_steps_summary for old tools
    summary_found = any("past_steps_summary" in m.get("content", "") for m in compacted)
    assert summary_found
