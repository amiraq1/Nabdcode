"""Phase 3 — Structural (+ optional Semantic) Evidence Verification.

Phase 3.1 hardening:
  - E-id extraction: if claim references E-ids, only those records are checked
  - No technical tokens + tools ran → reject (fail-closed)
  - max_evidence_records config threaded from AppContext → EvidenceLog → StructuralVerifier
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.evidence import (
    EvidenceLog,
    EvidenceRecord,
    VerifierError,
    StructuralVerifier,
    SemanticVerifier,
    VerificationResult,
    _extract_technical_tokens,
)


# ── Token extraction ─────────────────────────────────────────────────────

def test_extract_camelcase_tokens():
    """CamelCase identifiers like FastAPI must be extracted."""
    tokens = _extract_technical_tokens("The project uses FastAPI for the API layer")
    assert "fastapi" in tokens, f"Expected 'fastapi' in tokens, got {tokens}"


def test_extract_module_dotted_tokens():
    """Dotted module references like os.path must be extracted."""
    tokens = _extract_technical_tokens("It imports core.evidence and os.path")
    assert "core.evidence" in tokens, f"Expected 'core.evidence' in tokens, got {tokens}"


def test_extract_snake_case_tokens():
    """Snake_case identifiers must be extracted."""
    tokens = _extract_technical_tokens("The execute_shell function was called")
    assert "execute_shell" in tokens, f"Expected 'execute_shell' in tokens, got {tokens}"


def test_extract_file_paths():
    """File paths starting with / or ./ must be extracted."""
    tokens = _extract_technical_tokens("I read ./main.py and /etc/config.json")
    assert "./main.py" in tokens, f"Expected './main.py' in tokens, got {tokens}"
    assert "/etc/config.json" in tokens


def test_stopwords_filtered():
    """Generic English words must not appear as technical tokens."""
    tokens = _extract_technical_tokens("The code uses a file from the list")
    common_bad = {"the", "this", "file", "list", "code", "uses", "from"}
    assert not (tokens & common_bad), f"Stopwords leaked into tokens: {tokens}"


# ── L1 — StructuralVerifier ──────────────────────────────────────────────

def test_l1_claim_supported_pass():
    """Claim mentioning 'FastAPI' passes when evidence output contains 'fastapi'."""
    records = {
        "E-1": EvidenceRecord(
            evidence_id="E-1", evidence_type="shell", tool="execute_shell",
            command_or_path="grep fastapi", success=True,
            output_snippet="fastapi==0.104.0", covered_subjects=frozenset(),
        ),
    }
    result = StructuralVerifier.verify(
        claim="The project uses FastAPI version 0.104.0",
        records=records,
    )
    assert result.ok, f"Expected pass, got: {result.findings}"
    assert result.level == "L1"


def test_l1_claim_unsupported_reject():
    """Claim mentioning 'FastAPI' fails when evidence has no FastAPI content."""
    records = {
        "E-1": EvidenceRecord(
            evidence_id="E-1", evidence_type="filesystem", tool="file_system",
            command_or_path="main.py", success=True,
            output_snippet="def hello(): print('world')",
            covered_subjects=frozenset(),
        ),
    }
    result = StructuralVerifier.verify(
        claim="The project uses FastAPI",
        records=records,
    )
    assert not result.ok, f"Expected reject, got: {result.findings}"
    assert "fastapi" in str(result.findings).lower()


def test_l1_no_technical_tokens_rejects():
    """A claim with no distinctive technical tokens + substantive records → reject (fail-closed)."""
    records = {
        "E-1": EvidenceRecord(
            evidence_id="E-1", evidence_type="shell", tool="execute_shell",
            command_or_path="echo hello", success=True,
            output_snippet="hello world", covered_subjects=frozenset(),
        ),
    }
    result = StructuralVerifier.verify(
        claim="The output shows the result",
        records=records,
    )
    assert not result.ok, "No-token claim should reject when tools ran"
    assert "technical anchors" in str(result.findings).lower()
    assert result.scores == {}


def test_l1_empty_output_snippet_warns():
    """Successful records with empty output_snippet generate a finding but can still pass
    if command_or_path/covered_subjects match tokens."""
    records = {
        "E-1": EvidenceRecord(
            evidence_id="E-1", evidence_type="shell", tool="execute_shell",
            command_or_path="check_fastapi", success=True,
            output_snippet="", covered_subjects=frozenset({"check", "fastapi"}),
        ),
    }
    result = StructuralVerifier.verify(
        claim="Checked FastAPI with check_fastapi",
        records=records,
    )
    assert result.ok, "Should pass because covered_subjects contain matching tokens"
    has_empty_warning = any("empty output" in f.lower() for f in result.findings)
    assert has_empty_warning, "Should warn about empty output_snippet"


def test_l1_no_records_skips():
    """No records at all → L1 skip (pass)."""
    result = StructuralVerifier.verify(
        claim="The project uses FastAPI",
        records={},
    )
    assert result.ok


# ── L2 — SemanticVerifier stub ───────────────────────────────────────────

def test_l2_stub_fail_closed():
    """SemanticVerifier.verify() without an LLM callable must return fail-closed."""
    result = SemanticVerifier.verify(
        claim="test claim",
        records={},
    )
    assert not result.ok
    assert result.level == "L2"


# ── Integration: EvidenceLog.verify(claim=...) ──────────────────────────

def test_evidence_log_verify_l0_l1_integration_pass():
    """Full stack: records exist + claim supported → pass."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="check FastAPI version",
               success=True, output_snippet="fastapi==0.104.0")

    # Should not raise: require_tools=True but claim is supported
    log.verify(require_tools=True, claim="FastAPI version 0.104.0")


def test_evidence_log_verify_l1_reject():
    """Full stack: records exist but claim contradicts → VerifierError."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="main.py",
               success=True, output_snippet="def hello(): print('world')")

    try:
        log.verify(require_tools=True, claim="The project uses FastAPI")
        assert False, "Expected VerifierError"
    except VerifierError as e:
        msg = str(e).lower()
        assert "l1" in msg
        assert "fastapi" in msg


def test_evidence_log_verify_no_claim_skips_l1():
    """When claim is None, L1 is skipped and only L0 runs (backward compat)."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="something",
               success=True, output_snippet="some output")

    # Should not raise (same behavior as before Phase 3)
    log.verify(require_tools=True)


def test_evidence_log_verify_no_records_reject():
    """No records + require_tools=True must still reject (L0 unchanged)."""
    log = EvidenceLog()
    try:
        log.verify(require_tools=True, claim="some claim")
        assert False, "Expected VerifierError"
    except VerifierError as e:
        assert "no verified evidence" in str(e).lower()


def test_evidence_log_verify_chitchat_no_claim():
    """Chitchat (require_tools=False) with no claim must still pass L0."""
    log = EvidenceLog()
    log.verify(require_tools=False)  # should not raise


# ── The canonical FastAPI example from the requirements ──────────────────

def test_fastapi_claim_without_fastapi_evidence_rejected():
    """
    Claim: "uses FastAPI"
    Evidence: read_file main.py, content has no mention of FastAPI
    → L1 must reject
    """
    log = EvidenceLog()
    log.record(
        tool="file_system", command_or_path="main.py", success=True,
        output_snippet="""from core.config import AgentConfig
from core.logger import Logger
def main():
    pass""",
    )

    try:
        log.verify(require_tools=True, claim="The project uses FastAPI")
        assert False, "Expected VerifierError — no FastAPI in evidence"
    except VerifierError:
        pass  # Expected


def test_fastapi_claim_with_fastapi_evidence_passes():
    """
    Claim: "uses FastAPI"
    Evidence: read_file main.py, content includes FastAPI  
    → L1 must pass (at least 1 strong token matched)
    """
    log = EvidenceLog()
    log.record(
        tool="file_system", command_or_path="setup.py", success=True,
        output_snippet="""fastapi==0.104.0
uvicorn==0.24.0
from fastapi import FastAPI""",
    )

    log.verify(require_tools=True, claim="The project uses FastAPI version 0.104.0 with uvicorn")


# ── VerificationResult formatting ────────────────────────────────────────

def test_verification_result_to_error():
    """VerificationResult must format as a readable error message."""
    result = VerificationResult(
        ok=False,
        findings=["fastapi not found in evidence", "0/2 tokens matched"],
        level="L1",
        scores={"matches": 0, "total": 2, "overlap": 0.0},
    )
    msg = result.to_error("L1")
    assert "Evidence verification failed (L1)" in msg
    assert "fastapi not found" in msg


# ── Phase 3.1: E-id selection + soft-claim reject + max_records ─────────

def test_extract_evidence_ids_from_claim():
    """E-1, E-2 references in a claim must be extracted."""
    ids = StructuralVerifier._extract_referenced_evidence_ids(
        "As shown in E-1 and E-3, the project uses FastAPI"
    )
    assert ids == {"E-1", "E-3"}


def test_extract_no_evidence_ids_when_none_present():
    """A claim with no E-id references must return empty set."""
    ids = StructuralVerifier._extract_referenced_evidence_ids(
        "The project uses FastAPI"
    )
    assert ids == set()


def test_l1_eid_selection_only_referenced():
    """When claim references E-2, only E-2 is checked (not E-1)."""
    records = {
        "E-1": EvidenceRecord(
            evidence_id="E-1", evidence_type="shell", tool="execute_shell",
            command_or_path="echo wrong", success=True,
            output_snippet="wrong data", covered_subjects=frozenset(),
        ),
        "E-2": EvidenceRecord(
            evidence_id="E-2", evidence_type="shell", tool="execute_shell",
            command_or_path="grep fastapi", success=True,
            output_snippet="fastapi==0.104.0", covered_subjects=frozenset(),
        ),
    }
    # Claim references E-2 and content matches E-2 → pass
    result = StructuralVerifier.verify(
        claim="According to E-2, FastAPI version 0.104.0 is used",
        records=records,
    )
    assert result.ok, f"Expected pass (E-2 matches), got: {result.findings}"


def test_l1_eid_selection_nonexistent_ids_reject():
    """Claim references E-99 which doesn't exist → reject."""
    records = {
        "E-1": EvidenceRecord(
            evidence_id="E-1", evidence_type="shell", tool="execute_shell",
            command_or_path="echo hello", success=True,
            output_snippet="hello", covered_subjects=frozenset(),
        ),
    }
    result = StructuralVerifier.verify(
        claim="According to E-99, everything is fine",
        records=records,
    )
    assert not result.ok, "Should reject — E-99 doesn't exist"
    assert "E-99" in str(result.findings)


def test_l1_max_records_limits_selection():
    """Only the last N successful records should be considered."""
    records = {}
    for i in range(1, 21):  # 20 records
        records[f"E-{i}"] = EvidenceRecord(
            evidence_id=f"E-{i}", evidence_type="shell", tool="execute_shell",
            command_or_path="some_command", success=True,
            output_snippet=f"output_{i}", covered_subjects=frozenset(),
        )
    result = StructuralVerifier.verify(
        claim="output_1 content",
        records=records,
        max_records=5,  # Only last 5: E-16..E-20
    )
    # output_1 is in E-1 which is outside the last-5 window
    assert not result.ok, "E-1 should not be in the last-5 window"


def test_vague_claim_with_tools_ran_rejected():
    """Soft generic claim like 'the project looks good' after tools ran → reject."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="ls -la",
               success=True, output_snippet="file1.py  file2.py  README.md")
    log.record(tool="file_system", command_or_path="main.py",
               success=True, output_snippet="""from core.config import AgentConfig
def main():
    pass""")

    try:
        log.verify(require_tools=True, claim="The project looks good and is well structured")
        assert False, "Expected VerifierError — vague claim with tools ran"
    except VerifierError as e:
        msg = str(e).lower()
        assert "technical anchors" in msg


def test_eid_claim_with_supporting_content_passes():
    """Claim references E-2 and evidence content supports it → pass."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="main.py",
               success=True, output_snippet="""from core.config import AgentConfig""")
    log.record(tool="execute_shell", command_or_path="grep fastapi",
               success=True, output_snippet="fastapi==0.104.0 installed")
    log.record(tool="execute_shell", command_or_path="ls",
               success=False, output_snippet="permission denied")

    log.verify(require_tools=True, claim="According to E-2, FastAPI 0.104.0 is installed")


if __name__ == "__main__":
    test_extract_camelcase_tokens()
    test_extract_module_dotted_tokens()
    test_extract_snake_case_tokens()
    test_extract_file_paths()
    test_stopwords_filtered()
    test_l1_claim_supported_pass()
    test_l1_claim_unsupported_reject()
    test_l1_no_technical_tokens_rejects()
    test_l1_empty_output_snippet_warns()
    test_l1_no_records_skips()
    test_l2_stub_fail_closed()
    test_evidence_log_verify_l0_l1_integration_pass()
    test_evidence_log_verify_l1_reject()
    test_evidence_log_verify_no_claim_skips_l1()
    test_evidence_log_verify_no_records_reject()
    test_evidence_log_verify_chitchat_no_claim()
    test_fastapi_claim_without_fastapi_evidence_rejected()
    test_fastapi_claim_with_fastapi_evidence_passes()
    test_verification_result_to_error()
    test_extract_evidence_ids_from_claim()
    test_extract_no_evidence_ids_when_none_present()
    test_l1_eid_selection_only_referenced()
    test_l1_eid_selection_nonexistent_ids_reject()
    test_l1_max_records_limits_selection()
    test_vague_claim_with_tools_ran_rejected()
    test_eid_claim_with_supporting_content_passes()
    print("All Phase 3/3.1 tests passed.")
