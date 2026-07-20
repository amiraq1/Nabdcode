"""Wrapper around test execution to capture raw outputs directly into the EvidenceLog."""

from __future__ import annotations

import time
import uuid
from typing import Any

from core.evidence import EvidenceRecord
from core.parser import _validate_path
from core.kernel.subprocess_guard import default_guard


def run_tests_as_evidence(test_path: str, evidence_log: Any) -> str:
    """Run tests safely and record raw output directly as verifiable evidence."""
    # Ensure test_path does not escape workspace
    if test_path.endswith(".py") and not _validate_path(test_path):
        raise ValueError(f"Test path '{test_path}' escapes workspace or is invalid.")

    result = default_guard.run_infra(
        ["python3", "-m", "unittest", test_path, "-v"],
        timeout=120,
    )
    returncode, stdout, stderr = result
    raw = (stdout or "") + (stderr or "")
    evidence_log.add(
        EvidenceRecord(
            tool_name="run_tests",
            input=test_path,
            raw_output=raw,
            exit_code=returncode,
            timestamp=time.time(),
            call_id=str(uuid.uuid4()),
        )
    )
    return raw
