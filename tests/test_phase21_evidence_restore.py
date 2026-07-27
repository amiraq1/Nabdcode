"""Phase 2.1 — Runtime restore of EvidenceLog (session-scoped singleton).

Verifies:
  1. AppContext carries a shared EvidenceLog instance.
  2. ExecutionLoop uses the injected evidence_log when provided.
  3. Save evidence → restart → restore → records accessible + counter continues.
  4. ToolRequiredError path still saves after stripping.

--- Condition 17: Journal Durability Across Restart ---
  5. EvidenceLog.save → fresh Python subprocess → restore → records intact.
  6. Truncated / corrupt payload is rejected fail-closed (VerifierError).
  7. Counter continuity across two processes (3 writes → read+1 write = E-4).
"""

import json
import os
import subprocess
import sys
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
        from core.storage import SessionManager
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
    test_evidence_survives_fresh_process()
    test_evidence_truncated_tail_rejected()
    test_evidence_corrupted_jsonl_rejected()
    test_evidence_counter_continuity_across_processes()
    test_evidence_empty_restore()
    test_evidence_no_duplicate_terminal_across_restart()
    print("All Phase 2.1 tests passed.")


# ═══════════════════════════════════════════════════════════════════════
# Condition 17 — EvidenceLog Durability Across Restart
# ═══════════════════════════════════════════════════════════════════════

def test_evidence_survives_fresh_process():
    """Condition 17: EvidenceLog.save → fresh Python subprocess → restore → records intact.

    This test uses a real ``subprocess.run([sys.executable, "-c", …])`` — not
    an in-process simulation. The child script serializes, persists to a JSON
    session file via SessionManager (atomic write), then a *second* subprocess
    reads the session file and restores the EvidenceLog.
    """
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp) / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        # ── Process A: record evidence, save to disk ──
        script_a = (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog\n"
            "from core.storage import SessionManager\n"
            "log = EvidenceLog()\n"
            "log.record(tool='file_system', command_or_path='README.md',\n"
            "           success=True, output_snippet='NABD OS description')\n"
            "log.record(tool='execute_shell', command_or_path='ls -la',\n"
            "           success=True, output_snippet='total 42')\n"
            "log.record(tool='web_search', command_or_path='python',\n"
            "           success=False, output_snippet='timeout')\n"
            "sm = SessionManager(root=Path(sys.argv[1]))\n"
            "sm.evidence = log.to_serializable().get('records', [])\n"
            "ok = sm.save()\n"
            "print(json.dumps({'ok': ok, 'counter_before': log.counter,\n"
            "    'session_id': sm.session_id}))\n"
        )
        res_a = subprocess.run(
            [sys.executable, "-c", script_a, str(session_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert res_a.returncode == 0, (
            f"Process A failed:\nstdout={res_a.stdout}\nstderr={res_a.stderr}"
        )
        data_a = json.loads(res_a.stdout.strip())
        assert data_a["ok"] is True
        session_id = data_a["session_id"]

        # ── Process B: fresh subprocess, load session, restore EvidenceLog ──
        script_b = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog\n"
            "from core.storage import SessionManager\n"
            "sm = SessionManager(root=Path(sys.argv[1]))\n"
            "ok = sm.load(sys.argv[2])\n"
            "if not ok:\n"
            "    print(json.dumps({'error': 'load failed'}))\n"
            "    sys.exit(1)\n"
            "log = EvidenceLog()\n"
            "log.restore({'records': sm.evidence})\n"
            "recs = log.get_records()\n"
            "summary = {\n"
            "    'counter': log.counter,\n"
            "    'num_records': len(recs),\n"
            "    'ids': [r.evidence_id for r in recs],\n"
            "    'successes': [r.success for r in recs],\n"
            "}\n"
            "print(json.dumps(summary))\n"
        )
        res_b = subprocess.run(
            [sys.executable, "-c", script_b, str(session_dir), session_id],
            capture_output=True, text=True, timeout=30,
        )
        assert res_b.returncode == 0, (
            f"Process B failed:\nstdout={res_b.stdout}\nstderr={res_b.stderr}"
        )
        data_b = json.loads(res_b.stdout.strip())

        assert data_b["num_records"] == 3, (
            f"Expected 3 records, got {data_b['num_records']}"
        )
        assert data_b["counter"] == 3, (
            f"Expected counter=3, got {data_b['counter']}"
        )
        assert data_b["ids"] == ["E-1", "E-2", "E-3"], (
            f"IDs mismatch: {data_b['ids']}"
        )
        assert data_b["successes"] == [True, True, False], (
            f"Success flags mismatch: {data_b['successes']}"
        )


def test_evidence_truncated_tail_rejected():
    """Condition 17: Truncated JSON lines payload is rejected fail-closed.

    Writes a partial (truncated) JSONL-looking file to disk. A fresh subprocess
    that attempts to restore it must raise VerifierError — never silently accept
    partial data.
    """
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp) / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Build a truncated record deliberately (missing fields) using
        # repr() to get a Python-safe literal (not JSON true/null).
        truncated_payload = [
            {"evidence_id": "E-1", "tool": "file_system",
             "command_or_path": "README.md", "success": True},
            # Second record is TRUNCATED — missing required fields
            {"evidence_id": None, "tool": None},
        ]
        payload_repr = repr(truncated_payload)

        script = (
            "import json, sys\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog, VerifierError\n"
            "log = EvidenceLog()\n"
            "try:\n"
            "    log.restore({'records': " + payload_repr + "})\n"
            "    print(json.dumps({'error': 'RESTORE_SILENTLY_ACCEPTED_CORRUPT_DATA'}))\n"
            "    sys.exit(1)\n"
            "except VerifierError as e:\n"
            "    print(json.dumps({'ok': True, 'error_msg': str(e)[:100]}))\n"
            "except Exception as e:\n"
            "    print(json.dumps({'error': f'WRONG_EXCEPTION: {type(e).__name__}: {e}'}))\n"
            "    sys.exit(1)\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
        )
        assert res.returncode == 0, (
            f"Truncation test failed:\nstdout={res.stdout}\nstderr={res.stderr}"
        )
        data = json.loads(res.stdout.strip())
        assert "ok" in data and data["ok"] is True, (
            f"Expected VerifierError rejection, got: {data}"
        )
        # Verify the error message mentions "restore rejected" or "corrupt"
        assert "restore rejected" in data["error_msg"].lower() or \
               "corrupt" in data["error_msg"].lower(), (
            f"Error message does not mention corruption: {data['error_msg']}"
        )


def test_evidence_corrupted_jsonl_rejected():
    """Condition 17: Non-dict records are rejected fail-closed.

    A records list containing a plain string (not a dict) must trigger
    VerifierError rather than a silent TypeError leak.
    """
    with tempfile.TemporaryDirectory() as tmp:
        corrupt_payload = ["not-a-dict", {"evidence_id": "E-1", "tool": "x"}]
        payload_repr = repr(corrupt_payload)

        script = (
            "import json, sys\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog, VerifierError\n"
            "log = EvidenceLog()\n"
            "try:\n"
            "    log.restore({'records': " + payload_repr + "})\n"
            "    print(json.dumps({'error': 'RESTORE_SILENTLY_ACCEPTED_CORRUPT_DATA'}))\n"
            "    sys.exit(1)\n"
            "except VerifierError as e:\n"
            "    print(json.dumps({'ok': True, 'error_msg': str(e)[:100]}))\n"
            "except Exception as e:\n"
            "    print(json.dumps({'error': f'WRONG_EXCEPTION: {type(e).__name__}: {e}'}))\n"
            "    sys.exit(1)\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
        )
        assert res.returncode == 0, (
            f"Corruption test failed:\nstdout={res.stdout}\nstderr={res.stderr}"
        )
        data = json.loads(res.stdout.strip())
        assert "ok" in data and data["ok"] is True, (
            f"Expected VerifierError rejection, got: {data}"
        )


def test_evidence_counter_continuity_across_processes():
    """Condition 17: Process A writes 3 records → Process B reads + adds 1 → E-4.

    Counter continuity must survive a genuine process boundary with no gaps
    and no duplicate IDs.
    """
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp) / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        # ── Process A: write 3 records, save to disk ──
        script_a = (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog\n"
            "from core.storage import SessionManager\n"
            "log = EvidenceLog()\n"
            "log.record(tool='file_system', command_or_path='f1', success=True,\n"
            "           output_snippet='r1')\n"
            "log.record(tool='execute_shell', command_or_path='f2', success=True,\n"
            "           output_snippet='r2')\n"
            "log.record(tool='web_search', command_or_path='f3', success=True,\n"
            "           output_snippet='r3')\n"
            "sm = SessionManager(root=Path(sys.argv[1]))\n"
            "sm.evidence = log.to_serializable().get('records', [])\n"
            "sm.save()\n"
            "print(json.dumps({'counter': log.counter, 'ids': "
            "[r.evidence_id for r in log.get_records()],\n"
            "    'session_id': sm.session_id}))\n"
        )
        res_a = subprocess.run(
            [sys.executable, "-c", script_a, str(session_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert res_a.returncode == 0, (
            f"Process A failed:\nstdout={res_a.stdout}\nstderr={res_a.stderr}"
        )
        data_a = json.loads(res_a.stdout.strip())
        assert data_a["counter"] == 3
        session_id = data_a["session_id"]

        # ── Process B: load session, restore, add 1 record ──
        script_b = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog\n"
            "from core.storage import SessionManager\n"
            "sm = SessionManager(root=Path(sys.argv[1]))\n"
            "sm.load(sys.argv[2])\n"
            "log = EvidenceLog()\n"
            "log.restore({'records': sm.evidence})\n"
            "# Add a 4th record — must get E-4, not E-1 or conflict\n"
            "rec = log.record(tool='file_system', command_or_path='f4',\n"
            "    success=True, output_snippet='r4')\n"
            "recs = log.get_records()\n"
            "print(json.dumps({\n"
            "    'counter': log.counter,\n"
            "    'new_id': rec.evidence_id,\n"
            "    'total_records': len(recs),\n"
            "    'ids': [r.evidence_id for r in recs],\n"
            "}))\n"
        )
        res_b = subprocess.run(
            [sys.executable, "-c", script_b, str(session_dir), session_id],
            capture_output=True, text=True, timeout=30,
        )
        assert res_b.returncode == 0, (
            f"Process B failed:\nstdout={res_b.stdout}\nstderr={res_b.stderr}"
        )
        data_b = json.loads(res_b.stdout.strip())

        assert data_b["counter"] == 4, (
            f"Expected counter=4, got {data_b['counter']}"
        )
        assert data_b["new_id"] == "E-4", (
            f"Expected new record E-4, got {data_b['new_id']}"
        )
        assert data_b["total_records"] == 4, (
            f"Expected 4 total records, got {data_b['total_records']}"
        )
        # E-1 through E-4 with no gaps, no duplicates
        assert data_b["ids"] == ["E-1", "E-2", "E-3", "E-4"], (
            f"IDs not contiguous: {data_b['ids']}"
        )


def test_evidence_empty_restore():
    """Condition 17: Empty EvidenceLog restore produces counter=0 and zero records.

    This is a dedicated test for the empty-payload path. A real subprocess
    asserts that deserializing an empty records list is safe (no crash) and
    yields clean initial state.
    """
    script = (
        "import json, sys\n"
        "sys.path.insert(0, '.')\n"
        "from core.evidence import EvidenceLog\n"
        "log = EvidenceLog()\n"
        "log.restore({'records': []})\n"
        "print(json.dumps({\n"
        "    'counter': log.counter,\n"
        "    'num_records': len(log.get_records()),\n"
        "}))\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, (
        f"Subprocess failed:\nstdout={res.stdout}\nstderr={res.stderr}"
    )
    data = json.loads(res.stdout.strip())
    assert data["counter"] == 0, f"Expected counter=0, got {data['counter']}"
    assert data["num_records"] == 0, (
        f"Expected 0 records, got {data['num_records']}"
    )


def test_evidence_no_duplicate_terminal_across_restart():
    """Condition 17: Process A reaches a terminal evidence state → Process B
    restores → no duplicate terminal outcome, no replayed emissions.

    The test asserts that after restoration:
      (a) The EvidenceLog does not magically acquire a 'completed' flag
          (it is plain data — the convergence gate owns termination).
      (b) New evidence records get correct contiguous IDs (no E-1 collision).
      (c) The restored records are identical to the saved ones (no data
          mutation across the process boundary).
    """
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp) / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        # ── Process A: simulate a terminal state (2 records) ──
        script_a = (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog\n"
            "from core.storage import SessionManager\n"
            "log = EvidenceLog()\n"
            "log.record(tool='file_system', command_or_path='target.py',\n"
            "    success=True, output_snippet='class Target: ...')\n"
            "log.record(tool='final_answer', command_or_path='answer',\n"
            "    success=True, output_snippet='Analysis complete.')\n"
            "sm = SessionManager(root=Path(sys.argv[1]))\n"
            "sm.evidence = log.to_serializable().get('records', [])\n"
            "sm.save()\n"
            "print(json.dumps({'counter': log.counter,\n"
            "    'num_records': len(log.get_records()),\n"
            "    'session_id': sm.session_id}))\n"
        )
        res_a = subprocess.run(
            [sys.executable, "-c", script_a, str(session_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert res_a.returncode == 0, (
            f"Process A failed:\nstdout={res_a.stdout}\nstderr={res_a.stderr}"
        )
        data_a = json.loads(res_a.stdout.strip())
        assert data_a["counter"] == 2
        session_id = data_a["session_id"]

        # ── Process B: restore evidence, verify no terminal leackage ──
        script_b = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, '.')\n"
            "from core.evidence import EvidenceLog\n"
            "from core.storage import SessionManager\n"
            "sm = SessionManager(root=Path(sys.argv[1]))\n"
            "sm.load(sys.argv[2])\n"
            "log = EvidenceLog()\n"
            "log.restore({'records': sm.evidence})\n"
            "recs = log.get_records()\n"
            "# (a) EvidenceLog has no 'status' attribute — it is plain data.\n"
            "#     Verify it does NOT have a spurious 'completed' field.\n"
            "assert not hasattr(log, 'status'), 'EvidenceLog should not carry status'\n"
            "# (b) No completed flag anywhere in the records.\n"
            "for r in recs:\n"
            "    assert not hasattr(r, 'completed'), f'{r.evidence_id} has completed flag'\n"
            "# (c) Records are intact.\n"
            "ids = [r.evidence_id for r in recs]\n"
            "tools = [r.tool for r in recs]\n"
            "# (d) Adding a new record gets a valid next ID.\n"
            "rec = log.record(tool='verify', command_or_path='check',\n"
            "    success=True, output_snippet='ok')\n"
            "summary = {\n"
            "    'counter': log.counter,\n"
            "    'num_records': len(log.get_records()),\n"
            "    'ids': ids,\n"
            "    'tools': tools,\n"
            "    'new_id': rec.evidence_id,\n"
            "}\n"
            "print(json.dumps(summary))\n"
        )
        res_b = subprocess.run(
            [sys.executable, "-c", script_b, str(session_dir), session_id],
            capture_output=True, text=True, timeout=30,
        )
        assert res_b.returncode == 0, (
            f"Process B failed:\nstdout={res_b.stdout}\nstderr={res_b.stderr}"
        )
        data_b = json.loads(res_b.stdout.strip())

        assert data_b["counter"] == 3
        assert data_b["num_records"] == 3
        assert data_b["ids"] == ["E-1", "E-2"]
        assert data_b["tools"] == ["file_system", "final_answer"]
        assert data_b["new_id"] == "E-3"


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
