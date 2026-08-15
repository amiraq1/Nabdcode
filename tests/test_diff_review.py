from pathlib import Path
from types import SimpleNamespace

from core.diff_review import (
    approve_review,
    build_review,
    review_is_approved,
    run_review_tests,
    format_review,
    store_review,
)
from core.kernel.state import RuntimeState
from core.plan_apply import authorize_apply, record_plan, runtime_tool_block_reason


def test_build_review_redacts_secrets_and_calculates_risk(tmp_path):
    state = RuntimeState(session_id="review-1")
    record_plan(state, ["Update API token handling"])
    report = build_review(state, tmp_path)
    assert report["risk"] == "high"
    assert report["test_status"] == "not_applicable"

    edit = SimpleNamespace(
        path="config.py",
        additions=2,
        removals=1,
        diff="+api_key=SECRET_VALUE\n+normal change",
    )
    import core.diff_review as module
    original = module.peek_pending
    module.peek_pending = lambda: [edit]
    try:
        report = build_review(state, tmp_path)
    finally:
        module.peek_pending = original
    assert "SECRET_VALUE" not in report["pending_edits"][0]["diff_preview"]
    assert "<redacted>" in report["pending_edits"][0]["diff_preview"]


def test_review_run_uses_known_local_test_and_approval(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_config.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    state = RuntimeState(session_id="review-2")
    record_plan(state, ["Change config"])
    import core.diff_review as module
    original = module.peek_pending
    module.peek_pending = lambda: [SimpleNamespace(path="config.py", additions=1, removals=0, diff="+x")]
    try:
        report = run_review_tests(build_review(state, tmp_path), tmp_path)
    finally:
        module.peek_pending = original
    store_review(state, report)
    assert report["test_candidates"] == ["tests/test_config.py"]
    assert report["test_status"] == "passed"
    ok, _ = approve_review(state)
    assert ok is True
    assert review_is_approved(state) is True
    ok, _ = authorize_apply(state)
    assert ok is True


def test_new_plan_invalidates_previous_review_and_apply():
    state = RuntimeState(session_id="review-3")
    record_plan(state, ["First change"])
    report = build_review(state, Path.cwd())
    store_review(state, report)
    assert approve_review(state)[0] is True
    assert review_is_approved(state) is True

    record_plan(state, ["Changed scope"])
    assert review_is_approved(state) is False
    ok, message = authorize_apply(state)
    assert ok is False
    assert "review" in message.lower()


def test_format_review_is_structured_and_human_readable():
    output = format_review(
        {
            "revision": 4,
            "risk": "high",
            "risk_reasons": ["sensitive operation or credential keyword detected"],
            "files": ["config.py"],
            "additions": 2,
            "removals": 1,
            "plan_items": ["Review config"],
            "test_candidates": ["tests/test_config.py"],
            "test_status": "passed",
            "pending_edits": [
                {"path": "config.py", "additions": 2, "removals": 1, "diff_preview": "+token=<redacted>"}
            ],
        }
    )
    assert "DIFF REVIEW | PLAN REVISION 4 | RISK: HIGH" in output
    assert "Risk signals:" in output
    assert "Candidate tests:" in output
    assert "config.py (+2/-1)" in output
    assert "Decision: inspect this report before /review approve." in output


def test_apply_gate_requires_review_approval():
    state = RuntimeState(session_id="review-4")
    record_plan(state, ["Change file"])
    state.operation_mode = "apply"
    state.apply_authorized_revision = state.plan_revision
    reason = runtime_tool_block_reason("file_system", {"action": "write"}, state)
    assert reason is not None
    assert "review" in reason.lower()
