"""Git operation tools with automatic deterministic synchronization evidence logging."""

from __future__ import annotations

import subprocess
import time
import uuid
from typing import Any, Dict, Optional

from core.evidence import EvidenceRecord
from tools.base import BaseTool


def push_and_verify_evidence(
    evidence_log: Any,
    remote: str = "origin",
    branch: str = "main"
) -> Dict[str, EvidenceRecord]:
    """Execute git push and automatically record deterministic git diff verification evidence."""
    # 1. Execute real git push
    push_res = subprocess.run(
        ["git", "push", remote, branch],
        capture_output=True,
        text=True
    )
    push_raw = (push_res.stdout or "") + (push_res.stderr or "")
    push_rec = EvidenceRecord(
        tool_name="git_push",
        input=f"{remote} {branch}",
        raw_output=push_raw,
        exit_code=push_res.returncode,
        timestamp=time.time(),
        call_id=str(uuid.uuid4()),
    )
    evidence_log.add(push_rec)

    # 2. Automatically execute git diff HEAD origin/main without manual intervention
    diff_target = f"{remote}/{branch}"
    diff_res = subprocess.run(
        ["git", "diff", "HEAD", diff_target],
        capture_output=True,
        text=True
    )
    diff_raw = (diff_res.stdout or "") + (diff_res.stderr or "")
    diff_rec = EvidenceRecord(
        tool_name="git_diff",
        input=f"HEAD {diff_target}",
        raw_output=diff_raw,
        exit_code=diff_res.returncode,
        timestamp=time.time(),
        call_id=str(uuid.uuid4()),
    )
    evidence_log.add(diff_rec)

    return {
        "push_record": push_rec,
        "diff_record": diff_rec,
    }


class GitPushTool(BaseTool):
    """Tool that performs git push and auto-records git diff verification evidence."""

    name: str = "git_push"
    description: str = (
        "Push commits to a remote branch and automatically execute git diff HEAD origin/main "
        "to record verification evidence in evidence_log."
    )

    def execute(
        self,
        evidence_log: Optional[Any] = None,
        remote: str = "origin",
        branch: str = "main",
        **kwargs: Any
    ) -> Dict[str, Any]:
        if evidence_log is None:
            from core.evidence import EvidenceLog
            evidence_log = EvidenceLog()

        recs = push_and_verify_evidence(evidence_log, remote=remote, branch=branch)
        push_ok = recs["push_record"].success
        diff_ok = recs["diff_record"].success and recs["diff_record"].raw_output.strip() == ""

        status = "success" if (push_ok and diff_ok) else "error"
        return {
            "status": status,
            "output": {
                "push_output": recs["push_record"].raw_output,
                "diff_output": recs["diff_record"].raw_output,
                "diff_record_id": recs["diff_record"].evidence_id,
            },
        }
