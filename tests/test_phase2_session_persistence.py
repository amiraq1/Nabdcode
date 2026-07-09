"""Phase 2 — Session persistence for Todo + Evidence.

Verifies:
  1. TodoManager serialization roundtrip.
  2. EvidenceLog serialization roundtrip.
  3. EvidenceRecord to_dict/from_dict.
  4. SessionManager save/load with v2 fields.
  5. Backward compat: v1 session (no version) loads gracefully.
  6. Full session save/restore with todos + evidence.
  7. counter restoration on EvidenceLog.restore().
"""

import sys
import os
import json
import tempfile
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.todo import TodoManager, TodoStatus
from core.evidence import EvidenceLog, EvidenceRecord
from core.session import SessionManager


# ── TodoManager serialization ──────────────────────────────────────────────

def test_todo_serialization_roundtrip():
    mgr = TodoManager()
    mgr.set_plan(["step one", "step two", "step three"])
    mgr.mark_in_progress(1)
    mgr.mark_done(1, verification_note="verified by test")

    serialized = mgr.to_serializable()
    assert len(serialized) == 3

    restored = TodoManager()
    restored.restore(serialized)
    items = restored.all()
    assert len(items) == 3
    assert items[0].id == 1
    assert items[0].text == "step one"
    assert items[0].status == TodoStatus.DONE
    assert items[0].verification_note == "verified by test"
    assert items[1].status == TodoStatus.PENDING
    assert items[2].text == "step three"


def test_todo_empty_restore():
    mgr = TodoManager()
    mgr.restore([])
    assert mgr.all() == []


# ── EvidenceLog serialization ──────────────────────────────────────────────

def test_evidence_log_serialization_roundtrip():
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="echo hello", success=True, output_snippet="hello")
    log.record(tool="file_system", command_or_path="/tmp/test.txt", success=True, output_snippet="content")
    log.record(tool="web_search", command_or_path="python 3.13", success=False, output_snippet="timeout")

    serialized = log.to_serializable()
    assert "records" in serialized
    assert len(serialized["records"]) == 3

    restored = EvidenceLog()
    restored.restore(serialized)
    assert len(restored.records) == 3
    assert restored.counter == 3  # max ID from E-1, E-2, E-3

    # Verify content
    rec2 = restored.get("E-2")
    assert rec2 is not None
    assert rec2.tool == "file_system"
    assert rec2.success is True

    rec3 = restored.get("E-3")
    assert rec3 is not None
    assert rec3.success is False


def test_evidence_log_empty_restore():
    log = EvidenceLog()
    log.restore({"records": []})
    assert len(log.records) == 0
    assert log.counter == 0


def test_evidence_record_to_dict_from_dict():
    rec = EvidenceRecord(
        evidence_id="E-42",
        evidence_type="shell",
        tool="execute_shell",
        command_or_path="ls -la",
        success=True,
        output_snippet="file1.txt",
        covered_subjects=frozenset({"ls", "la"}),
    )
    d = rec.to_dict()
    assert d["evidence_id"] == "E-42"
    assert d["covered_subjects"] == ["la", "ls"]  # sorted

    restored = EvidenceRecord.from_dict(d)
    assert restored == rec
    assert restored.covered_subjects == frozenset({"ls", "la"})


# ── SessionManager v2 save/load ──────────────────────────────────────────

def test_session_manager_v2_save_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sm = SessionManager(root=root)
        sm.messages = [{"role": "user", "content": "hello"}]
        sm.todos = [{"id": 1, "text": "do something", "status": "pending", "verification_note": ""}]
        sm.evidence = [{
            "evidence_id": "E-1",
            "evidence_type": "shell",
            "tool": "execute_shell",
            "command_or_path": "echo hi",
            "success": True,
            "output_snippet": "hi",
            "covered_subjects": ["hi"],
        }]
        assert sm.save()

        # Load into a fresh manager
        sm2 = SessionManager(root=root)
        assert sm2.load(sm.session_id)
        assert sm2.messages == sm.messages
        assert sm2.todos == sm.todos
        assert sm2.evidence == sm.evidence


def test_session_manager_v1_backward_compat():
    """v1 session files (no version/todos/evidence fields) must load cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sid = "sess_v1test_20250101000000"
        file_path = root / f"{sid}.json"
        v1_data = {
            "session_id": sid,
            "updated_at": "2025-01-01T00:00:00+00:00",
            "messages": [{"role": "user", "content": "v1 prompt"}],
            # no "version", no "todos", no "evidence_records"
        }
        file_path.write_text(json.dumps(v1_data), encoding="utf-8")

        sm = SessionManager(root=root)
        assert sm.load(sid)
        assert len(sm.messages) == 1
        assert sm.todos == []   # default, not None
        assert sm.evidence == []  # default, not None


# ── Full session save/restore (main.py logic) ────────────────────────────

def test_full_session_save_and_restore():
    """Simulate main.py's save-after-turn and restore-on-startup logic."""
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp)

        # ── Simulate a run ──
        sm = SessionManager(root=session_dir)
        sm.messages = [{"role": "user", "content": "analyze project"}, {"role": "assistant", "content": "done"}]

        # Simulate EvidenceLog with 2 records
        elog = EvidenceLog()
        elog.record(tool="execute_shell", command_or_path="ls -la", success=True, output_snippet="file1.txt")
        elog.record(tool="file_system", command_or_path="main.py", success=True, output_snippet="def main():")

        # Simulate TodoManager with 3 items
        tman = TodoManager()
        tman.set_plan(["list files", "read main", "summarize"])
        tman.mark_done(1, verification_note="done")

        # Save (same as main.py after each turn)
        sm.todos = tman.to_serializable()
        sm.evidence = elog.to_serializable().get("records", [])
        sm.save()

        # ── Restore (same as main.py on startup) ──
        latest_id = SessionManager.get_latest_session(session_dir)
        assert latest_id is not None

        latest_path = session_dir / f"{latest_id}.json"
        data = json.loads(latest_path.read_text(encoding="utf-8"))

        # Verify version
        assert data.get("version") == 2

        # Verify todos
        assert "todos" in data
        assert len(data["todos"]) == 3
        assert data["todos"][0]["status"] == "done"
        assert data["todos"][0]["verification_note"] == "done"

        restored_tman = TodoManager()
        restored_tman.restore(data["todos"])
        assert len(restored_tman.all()) == 3
        assert restored_tman.all()[0].status == TodoStatus.DONE

        # Verify evidence
        assert "evidence_records" in data
        assert len(data["evidence_records"]) == 2
        assert data["evidence_records"][0]["evidence_id"] == "E-1"
        assert data["evidence_records"][0]["success"] is True

        restored_elog = EvidenceLog()
        restored_elog.restore({"records": data["evidence_records"]})
        assert len(restored_elog.records) == 2
        assert restored_elog.get("E-1") is not None
        assert restored_elog.get("E-2") is not None


def test_evidence_log_counter_continuity():
    """After restore, next record gets the next sequential ID."""
    serialized = {"records": [
        {"evidence_id": "E-5", "evidence_type": "shell", "tool": "execute_shell",
         "command_or_path": "echo", "success": True, "output_snippet": "ok",
         "covered_subjects": []},
    ]}
    log = EvidenceLog()
    log.restore(serialized)
    assert log.counter == 5

    rec = log.record(tool="execute_shell", command_or_path="next", success=True, output_snippet="next")
    assert rec.evidence_id == "E-6"


if __name__ == "__main__":
    test_todo_serialization_roundtrip()
    test_todo_empty_restore()
    test_evidence_log_serialization_roundtrip()
    test_evidence_log_empty_restore()
    test_evidence_record_to_dict_from_dict()
    test_session_manager_v2_save_and_load()
    test_session_manager_v1_backward_compat()
    test_full_session_save_and_restore()
    test_evidence_log_counter_continuity()
    print("All Phase 2 tests passed.")
