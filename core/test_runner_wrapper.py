"""Wrapper around test execution to capture raw outputs directly into the EvidenceLog."""

from __future__ import annotations

import subprocess
import time
import uuid
from typing import Any

from core.evidence import EvidenceRecord
from core.parser import _validate_path


def run_tests_as_evidence(test_path: str, evidence_log: Any) -> str:
    """Run tests safely and record raw output directly as verifiable evidence."""
    # Ensure test_path does not escape workspace
    if test_path.endswith(".py") and not _validate_path(test_path):
        raise ValueError(f"Test path '{test_path}' escapes workspace or is invalid.")

    result = subprocess.run(
        ["python3", "-m", "unittest", test_path, "-v"],
        capture_output=True,
        text=True,
    )
    raw = (result.stdout or "") + (result.stderr or "")
    evidence_log.add(
        EvidenceRecord(
            tool_name="run_tests",
            input=test_path,
            raw_output=raw,
            exit_code=result.returncode,
            timestamp=time.time(),
            call_id=str(uuid.uuid4()),
        )
    )
    return raw
