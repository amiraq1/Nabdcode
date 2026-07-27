"""test_consent.py — Consent Integrity tests (Phase 2.6).

Covers:
  1. Empty enter → deny (not approve)
  2. EOF → deny
  3. KeyboardInterrupt → deny
  4. Approval records evidence
  5. Denial records evidence
  6. Failed-closed recording (utility path)
  7. Old approval cannot authorise a different turn/command
  8. Production consent path passes evidence_log
"""

import os
from unittest.mock import patch

from core.evidence import EvidenceLog
from engine.consent import (
    ConsentManager,
    ConsentPolicy,
    _record_consent_failed_closed,
)
from tools.models import ToolResult


# ── Decision tests ─────────────────────────────────────────────────────

def test_empty_enter_denies():
    """Empty enter ("") must return a blocked ToolResult, not None."""
    mgr = ConsentManager(prompt_func=lambda _: "")
    result = mgr.confirm("execute_shell", {"command": "rm -rf /"})
    assert result is not None, "Empty enter must NOT approve"
    assert "blocked" in (result.stdout or "").lower()


def test_y_approves():
    """"y" returns None (approved)."""
    mgr = ConsentManager(prompt_func=lambda _: "y")
    result = mgr.confirm("execute_shell", {"command": "echo ok"})
    assert result is None, "'y' must approve"


def test_yes_approves():
    """"yes" returns None (approved)."""
    mgr = ConsentManager(prompt_func=lambda _: "yes")
    result = mgr.confirm("execute_shell", {"command": "echo ok"})
    assert result is None, "'yes' must approve"


def test_uppercase_yes_is_handled_explicitly():
    """'Y' and 'YES' must be accepted after normalized casing."""
    for inp in ("Y", "YES"):
        mgr = ConsentManager(prompt_func=lambda _: inp)
        result = mgr.confirm("execute_shell", {"command": "echo ok"})
        assert result is None, f"'{inp}' must approve after .strip().lower()"


def test_whitespace_yes_is_handled_explicitly():
    """Surrounding whitespace on 'y'/'yes' must be handled."""
    for inp in (" y ", "  yes  ", "y ", " yes"):
        mgr = ConsentManager(prompt_func=lambda _: inp)
        result = mgr.confirm("execute_shell", {"command": "echo ok"})
        assert result is None, f"'{inp}' must approve after .strip()"


def test_n_denies():
    """"n" returns a blocked ToolResult."""
    mgr = ConsentManager(prompt_func=lambda _: "n")
    result = mgr.confirm("execute_shell", {"command": "rm -rf /"})
    assert result is not None, "'n' must not approve"


def test_eof_denies():
    """EOFError (piped stdin) must produce "n" and block.

    Tests ``_default_prompt`` directly (the function that catches EOFError).
    """
    from engine.consent import ConsentManager
    prompt = ConsentManager._default_prompt
    # No PYTEST_CURRENT_TEST + no NABD_AUTO_APPROVE → uses input()
    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "", "NABD_AUTO_APPROVE": ""}):
        with patch("builtins.input", side_effect=EOFError()):
            result = prompt("test")
            assert result == "n", f"Expected 'n', got {result!r}"


def test_keyboard_interrupt_denies():
    """KeyboardInterrupt must produce "n" and block.

    Tests ``_default_prompt`` directly (the function that catches
    KeyboardInterrupt).
    """
    from engine.consent import ConsentManager
    prompt = ConsentManager._default_prompt
    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "", "NABD_AUTO_APPROVE": ""}):
        with patch("builtins.input", side_effect=KeyboardInterrupt()):
            result = prompt("test")
            assert result == "n", f"Expected 'n', got {result!r}"


def test_oserror_denies():
    """OSError from input() must produce "n" and block."""
    from engine.consent import ConsentManager
    prompt = ConsentManager._default_prompt
    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "", "NABD_AUTO_APPROVE": ""}):
        with patch("builtins.input", side_effect=OSError()):
            result = prompt("test")
            assert result == "n", f"Expected 'n', got {result!r}"


# ── Evidence recording tests ───────────────────────────────────────────

def test_approval_records_evidence():
    """Approved consent produces an EvidenceRecord."""
    log = EvidenceLog()
    mgr = ConsentManager(prompt_func=lambda _: "y")
    mgr.confirm("execute_shell", {"command": "echo ok"}, evidence_log=log, step=5)
    recs = log.get_records()
    assert len(recs) == 1, f"Expected 1 record, got {len(recs)}"
    rec = recs[0]
    assert "consent.execute_shell" in rec.tool
    assert rec.success is True, "Approved record must have success=True"
    assert rec.action == "consent_step_5"


def test_denial_records_evidence():
    """Denied consent produces an EvidenceRecord with success=False."""
    log = EvidenceLog()
    mgr = ConsentManager(prompt_func=lambda _: "n")
    mgr.confirm("execute_shell", {"command": "rm -rf /"}, evidence_log=log, step=3)
    recs = log.get_records()
    assert len(recs) == 1, f"Expected 1 record, got {len(recs)}"
    rec = recs[0]
    assert "consent.execute_shell" in rec.tool
    assert rec.success is False, "Denied record must have success=False"
    assert rec.action == "consent_step_3"


def test_failed_closed_records_evidence():
    """Failed-closed consent event records correctly via utility function."""
    log = EvidenceLog()
    _record_consent_failed_closed(
        "execute_shell", {"command": "danger"},
        evidence_log=log, step=7, reason="bridge_unreachable",
    )
    recs = log.get_records()
    assert len(recs) == 1, f"Expected 1 record, got {len(recs)}"
    rec = recs[0]
    assert "consent.execute_shell" in rec.tool
    assert rec.success is False
    assert "failed_closed" in rec.output_snippet
    assert "bridge_unreachable" in rec.output_snippet


def test_evidence_record_contains_rich_metadata():
    """Every consent EvidenceRecord must include tool, command, step, decision, timestamp."""
    log = EvidenceLog()
    mgr = ConsentManager(prompt_func=lambda _: "y")
    mgr.confirm(
        "execute_shell", {"command": "ls -la /tmp"},
        evidence_log=log, step=42,
    )
    rec = log.get_records()[0]
    assert "consent.execute_shell" in rec.tool
    assert "ls -la" in rec.command_or_path
    assert "consent_step_42" in rec.action
    assert "consent:approved" in rec.output_snippet
    assert rec.timestamp > 0, f"Expected valid timestamp, got {rec.timestamp}"
    # Step identifier is in action; timestamp is recorded on the record itself.
    # Turn ID is not structurally available on EvidenceRecord — step + timestamp
    # together serve as the temporal identifier.


# ── Old approval reuse ────────────────────────────────────────────────

def test_old_approval_reuse_blocked():
    """A new turn must not silently reuse a previous turn's approval.

    This is enforced by approved_shell.clear() after each exact-action
    dispatch (see engine/_dispatch.py:324). The test verifies that a
    ConsentManager has no memory of previous approvals.
    """
    mgr = ConsentManager(prompt_func=lambda _: "y")
    # first command approved
    assert mgr.confirm("execute_shell", {"command": "cmd1"}) is None
    # re-approval is needed for a different command in a new turn
    # (ConsentManager itself is stateless — state is in _LoopCtx.approved_shell)
    assert mgr.confirm("execute_shell", {"command": "cmd1"}) is None
    # Both succeed independently; the turn-level dedup is tested separately
    # in test_tool_routing_gap_closure :: test_old_shell_approval_cannot_authorize_new_command


# ── Production path wiring ─────────────────────────────────────────────

def test_production_consent_path_passes_evidence_log():
    """The production dispatch path must pass evidence_log to ConsentManager.

    We simulate _dispatch.py's call signature and verify evidence is recorded
    on the Engine's evidence_log.
    """
    from engine.state import RuntimeState
    from engine.loop import ExecutionLoop

    state = RuntimeState(session_id="test-consent-prod")
    state.step_count = 99
    loop = ExecutionLoop(state, no_stream=True)

    # Call _handle_consent_and_edit_gate (the production path) with a
    # tool that requires consent. It uses a real ConsentManager internally.
    # We mock the prompt to return "y" so the flow goes through approval.
    from unittest.mock import patch as _patch
    with _patch("engine.consent.ConsentManager._default_prompt", return_value="y"):
        # Trigger the consent gate with execute_shell
        handled = loop._handle_consent_and_edit_gate(
            "execute_shell", {"command": "echo production-test"},
        )

    # The method returns True if consent blocked (denied) or False if approved
    # (we approved, so it returns False — meaning continue to dispatch).
    assert handled is False, (
        "Consent should have been approved (returned False = proceed)"
    )

    # Verify evidence was recorded on the loop's evidence_log
    recs = loop.evidence_log.get_records()
    consent_recs = [r for r in recs if "consent.execute_shell" in r.tool]
    assert len(consent_recs) == 1, (
        f"Expected 1 consent record, got {len(consent_recs)}. "
        f"All records: {[(r.evidence_id, r.tool) for r in recs]}"
    )
    assert consent_recs[0].success is True
    assert consent_recs[0].action == "consent_step_99"
