"""Regression: the exact DAG of claims from the production hallucination.

These tests lock the fix for the Path-Claim Gate bypass:
the agent's architecture self-analysis reported files that do not exist
on disk (engine/personas.py, tools/handoff.py, multi_agent/orchestrator.py).
The disk-existence backstop must reject them, while real files pass.
"""

import pytest
from pathlib import Path

from core.verifier import verify_report, check_path_existence_claim


class MockEvidence:
    def __init__(self, records=None):
        self._records = records or []

    def get_records(self):
        return self._records


HALLUCINATED = "engine/personas.py with ROLE_TOOL_ALLOWLIST"
REAL_PATH = "core/verifier.py"
NONE_CLAIMED = "I am a simple chat message with no paths."


def test_rejects_hallucinated_file():
    """engine/personas.py must be rejected — it does not exist on disk."""
    result = check_path_existence_claim(HALLUCINATED, Path.cwd(), MockEvidence())
    assert not result.passed
    assert any("personas.py" in c for c in result.unsupported_claims)


def test_accepts_real_file():
    """core/verifier.py exists on disk — must pass."""
    result = check_path_existence_claim(REAL_PATH, Path.cwd(), MockEvidence())
    assert result.passed


def test_no_claims_passes():
    """A report with zero path claims passes vacuously."""
    result = check_path_existence_claim(NONE_CLAIMED, Path.cwd(), MockEvidence())
    assert result.passed


def test_wrong_multi_agent_path():
    """multi_agent/orchestrator.py does not exist (correct: core/...)."""
    result = check_path_existence_claim(
        "multi_agent/orchestrator.py", Path.cwd(), MockEvidence()
    )
    assert not result.passed


def test_rejects_nonexistent_handoff():
    """tools/handoff.py does not exist on disk."""
    result = check_path_existence_claim(
        "tools/handoff.py", Path.cwd(), MockEvidence()
    )
    assert not result.passed


def test_events_mislocated_path():
    """engine/events.py does not exist (correct: core/kernel/events.py)."""
    result = check_path_existence_claim(
        "engine/events.py", Path.cwd(), MockEvidence()
    )
    assert not result.passed


def test_version_string_not_flagged():
    """Version-ish tokens like '3.11' must not be treated as paths."""
    result = check_path_existence_claim(
        "requires python 3.11", Path.cwd(), MockEvidence()
    )
    assert result.passed


def test_verify_report_still_rejects_hallucinated():
    """verify_report must also flag a never-read hallucinated path."""
    result = verify_report(HALLUCINATED, MockEvidence())
    assert not result.passed
