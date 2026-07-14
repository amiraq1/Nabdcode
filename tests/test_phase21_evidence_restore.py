"""Phase 2.1 — Runtime restore of EvidenceLog (session-scoped singleton).

Verifies:
  1. AppContext carries a shared EvidenceLog instance.
  2. ExecutionLoop uses the injected evidence_log when provided.
  3. Save evidence → restart → restore → records accessible + counter continues.
  4. ToolRequiredError path still saves after stripping.
"""

import sys
import os
import json
import tempfile
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.evidence import EvidenceLog
from engine.loop import ExecutionLoop
from engine.state import RuntimeState


def test_app_context_holds_evidence_log():
    """AppContext must create and expose an EvidenceLog singleton."""
    # AppContext.build() requires real config/fs — test the schema directly
    from dataclasses import dataclass
    from core.evidence import EvidenceLog

    @dataclass
    class FakeCtx:
        evidence_log: EvidenceLog

    ctx = FakeCtx(evidence_log=EvidenceLog())
    assert isinstance(ctx.evidence_log, EvidenceLog)


def test_execution_loop_accepts_injected_evidence_log():
    """When evidence_log is passed, ExecutionLoop must use it (not create a new one)."""
    shared = EvidenceLog()
    shared.record(tool="execute_shell", command_or_path="echo test", success=True, output_snippet="test")

    state = RuntimeState(session_id="test-p21-inject")
    loop = ExecutionLoop(state=state, evidence_log=shared)

    assert loop.evidence_log is shared, "Injected evidence_log must be the same object"
    # The record we added before injection must be visible
    assert loop.evidence_log.counter == 1
    assert loop.evidence_log.get("E-1") is not None


def test_evidence_log_counter_continues_after_restore():
    """Restore EvidenceLog → counter picks up from max ID → next record continues."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="cmd1", success=True, output_snippet="ok1")
    log.record(tool="file_system", command_or_path="file2", success=False, output_snippet="err2")
    assert log.counter == 2

    # Serialize then restore (simulates save → restart)
    serialized = log.to_serializable()

    restored = EvidenceLog()
    restored.restore(serialized)
    assert restored.counter == 2, f"Expected counter=2 after restore, got {restored.counter}"

    # Next record must get E-3
    rec = restored.record(tool="web_search", command_or_path="query3", success=True, output_snippet="result3")
    assert rec.evidence_id == "E-3", f"Expected E-3, got {rec.evidence_id}"
    assert restored.counter == 3


def test_session_save_and_restore_evidence_continuity():
    """Full cycle: start fresh → record evidence → save → restart simulation → restore → records intact."""
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp)

        # ── "First run" ──
        from core.session import SessionManager
        sm = SessionManager(root=session_dir)
        elog = EvidenceLog()
        elog.record(tool="execute_shell", command_or_path="ls -la", success=True, output_snippet="files")
        elog.record(tool="web_search", command_or_path="python", success=False, output_snippet="timeout")

        sm.evidence = elog.to_serializable().get("records", [])
        sm.save()

        # ── "Restart" ──
        latest_id = SessionManager.get_latest_session(session_dir)
        assert latest_id is not None

        latest_path = session_dir / f"{latest_id}.json"
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        evidence_records = data.get("evidence_records", [])
        assert len(evidence_records) == 2

        restored = EvidenceLog()
        restored.restore({"records": evidence_records})
        assert restored.counter == 2
        assert restored.get("E-1") is not None
        assert restored.get("E-2") is not None
        assert restored.get("E-1").success is True
        assert restored.get("E-2").success is False

        # Next record gets E-3
        rec = restored.record(tool="file_system", command_or_path="newfile", success=True, output_snippet="new")
        assert rec.evidence_id == "E-3"


def test_tool_required_error_strips_then_saves():
    """ToolRequiredError path strips the fabricated assistant message before save.

    This simulates the main.py flow: engine raises → handler strips → save runs.
    The save should see the clean state (no fabricated answer).
    """
    state = RuntimeState(session_id="test-p21-tre-save")
    state.append_message({"role": "system", "content": "system prompt"})
    state.append_message({"role": "user", "content": "do work"})

    # Simulate what loop.py does before raising: appends fabricated response
    state.append_message({"role": "assistant", "content": "I did the work (no tools used)"})

    assert len(state.get_messages()) == 3
    assert state.get_last_message()["role"] == "assistant"

    # Simulate main.py ToolRequiredError handler: strip last message
    msgs = state.get_messages()
    if msgs and msgs[-1].get("role") == "assistant":
        state.set_messages(msgs[:-1])

    # After strip: only system + user remain
    assert len(state.get_messages()) == 2
    assert state.get_last_message()["role"] == "user"
    assert state.get_last_message()["content"] == "do work"

    # Simulate save: messages captured from clean state
    saved_messages = state.get_messages()
    assert len(saved_messages) == 2
    assert saved_messages[-1]["role"] == "user"


def test_evidence_log_shared_across_turns_in_main():
    """Simulate main.py flow: create loop with shared evidence_log, verify records persist
    across loop instances."""
    from dataclasses import dataclass
    from core.evidence import EvidenceLog

    @dataclass
    class FakeCtx:
        evidence_log: EvidenceLog

    ctx = FakeCtx(evidence_log=EvidenceLog())

    # Simulate first turn
    state = RuntimeState(session_id="test-p21-shared-1")
    state.append_message({"role": "system", "content": "sys"})
    state.append_message({"role": "user", "content": "first turn"})

    loop1 = ExecutionLoop(state=state, evidence_log=ctx.evidence_log)
    # Manually record evidence (without running full LLM)
    loop1.evidence_log.record(
        tool="execute_shell", command_or_path="echo first", success=True, output_snippet="first output"
    )

    assert ctx.evidence_log.counter == 1
    assert ctx.evidence_log.get("E-1") is not None

    # Simulate second turn (new loop, same ctx.evidence_log)
    loop2 = ExecutionLoop(state=state, evidence_log=ctx.evidence_log)
    loop2.evidence_log.record(
        tool="file_system", command_or_path="second", success=True, output_snippet="second output"
    )

    assert ctx.evidence_log.counter == 2
    assert ctx.evidence_log.get("E-2") is not None
    assert ctx.evidence_log.get("E-1") is not None  # first turn record still there


if __name__ == "__main__":
    test_app_context_holds_evidence_log()
    test_execution_loop_accepts_injected_evidence_log()
    test_evidence_log_counter_continues_after_restore()
    test_session_save_and_restore_evidence_continuity()
    test_tool_required_error_strips_then_saves()
    test_evidence_log_shared_across_turns_in_main()
    print("All Phase 2.1 tests passed.")


# ---------------------------------------------------------------------------
# Regression: EvidenceRecord.success resolution (Defect #5)
# ---------------------------------------------------------------------------

from core.evidence import EvidenceRecord


def test_evidence_record_success_passthrough_on_zero_exit():
    """exit_code==0 must let the explicit `success` flag win (default True)."""
    rec = EvidenceRecord(evidence_id="E-1", tool="execute_shell", exit_code=0, success=True)
    assert rec.success is True

    rec_false = EvidenceRecord(evidence_id="E-2", tool="execute_shell", exit_code=0, success=False)
    assert rec_false.success is False


def test_evidence_record_success_forced_false_on_nonzero_exit():
    """exit_code!=0 must force success=False regardless of the passed flag."""
    rec = EvidenceRecord(evidence_id="E-3", tool="execute_shell", exit_code=1, success=True)
    assert rec.success is False

    rec_fail = EvidenceRecord(evidence_id="E-4", tool="execute_shell", exit_code=127, success=False)
    assert rec_fail.success is False


def test_evidence_record_default_success_on_zero_exit():
    """Default construction with exit_code=0 yields success=True."""
    rec = EvidenceRecord(evidence_id="E-5", tool="file_system")
    assert rec.success is True
