"""Independent, non-LLM deterministic verifier and rejection gate against fake success claims."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.parser import get_workspace_root


@dataclass
class VerificationResult:
    passed: bool
    unsupported_claims: List[str] = field(default_factory=list)
    details: str = ""


def _extract_claims(report_text: str) -> Dict[str, List[str]]:
    """Extract measurable claims from the report text."""
    return {
        "numbers": re.findall(r"\b\d+\b", report_text),
        "file_paths": re.findall(r"[\w/\-]+\.\w+", report_text),
        "commit_hashes": re.findall(r"\b[0-9a-f]{7,40}\b", report_text),
    }


def verify_report(report_text: str, evidence_log: Any) -> VerificationResult:
    """Verify report claims against evidence log raw outputs."""
    claims = _extract_claims(report_text)
    records = evidence_log.get_records()
    raw_outputs = " ".join(getattr(r, "raw_output", getattr(r, "output_snippet", "")) for r in records)

    unsupported = []

    # Numbers
    for num in claims["numbers"]:
        if num not in raw_outputs:
            unsupported.append(f"Unsupported number: {num}")

    # File paths
    for path in claims["file_paths"]:
        if path not in raw_outputs:
            unsupported.append(f"Unsupported path: {path}")

    # Commit hashes
    for h in claims["commit_hashes"]:
        if h not in raw_outputs:
            unsupported.append(f"Unsupported commit hash: {h}")

    passed = len(unsupported) == 0
    return VerificationResult(
        passed=passed,
        unsupported_claims=unsupported,
        details="All claims are supported by evidence." if passed else f"{len(unsupported)} unsupported claim(s).",
    )


def _count_from_tool_result(records: List[Any], tool_name: str) -> Optional[str]:
    """Return the raw output from specific tool records."""
    for r in records:
        if getattr(r, "tool_name", getattr(r, "tool", "")) == tool_name:
            return getattr(r, "raw_output", getattr(r, "output_snippet", ""))
    return None


def check_file_count_claim(report_text: str, evidence_log: Any) -> VerificationResult:
    """Check claims regarding .py file counts against actual file listing/search tool output."""
    claimed = re.search(
        r"(?:(\d+)\s*(?:ملف|ملفات|files?)\s*\.py|(?:عدد\s+)?(?:ملف|ملفات|files?)\s*\.py[^\d]*(\d+))",
        report_text,
        re.IGNORECASE,
    )
    if not claimed:
        return VerificationResult(True, [], "No file count claim present.")

    claimed_num = int(claimed.group(1) or claimed.group(2))
    records = [
        r for r in evidence_log.get_records()
        if getattr(r, "tool_name", getattr(r, "tool", "")) in ("find_files", "list_files", "file_system", "execute_shell")
    ]

    if not records:
        return VerificationResult(
            False,
            [f"Claim 'file count = {claimed_num}' with no find_files/list_files call"],
            "No tool evidence supports this claim at all."
        )

    # Actual count = number of non-empty lines in the tool output
    actual_num = sum(
        len([line for line in getattr(r, "raw_output", getattr(r, "output_snippet", "")).strip().splitlines() if line.strip()])
        for r in records
    )

    if actual_num != claimed_num:
        return VerificationResult(
            False,
            [f"Claimed count={claimed_num} but actual count from evidence={actual_num}"],
            "Direct numeric conflict — fabricated report."
        )
    return VerificationResult(True, [], f"Count {claimed_num} matches actual tool output.")


def check_commit_count_claim(report_text: str, evidence_log: Any) -> VerificationResult:
    """Check commit claims against git_log actual output."""
    claimed = re.findall(r"commit\s*\d*[:：]\s*[\"'](.+?)[\"']", report_text)
    records = [
        r for r in evidence_log.get_records()
        if getattr(r, "tool_name", getattr(r, "tool", "")) == "git_log"
    ]

    if not records:
        if claimed:
            return VerificationResult(
                False,
                [f"{len(claimed)} commit messages mentioned with no git_log call"],
                "Commits entirely fabricated — no git_log call in evidence_log."
            )
        return VerificationResult(True, [], "No commit claim present.")

    actual_output = "\n".join(getattr(r, "raw_output", getattr(r, "output_snippet", "")) for r in records)
    unsupported = [msg for msg in claimed if msg not in actual_output]

    if unsupported:
        return VerificationResult(
            False,
            [f"Fabricated commit message: '{m}'" for m in unsupported],
            f"{len(unsupported)} of {len(claimed)} commit messages not found in actual git_log output."
        )
    return VerificationResult(True, [], "All commit messages match git_log.")


def check_test_count_claim(report_text: str, evidence_log: Any) -> VerificationResult:
    """Check claims regarding test run counts against actual run_tests tool output."""
    claimed = re.search(
        r"(?:Ran\s+(\d+)\s+tests?|تشغيل\s+(\d+)\s+اختبار|(\d+)\s+اختبار)",
        report_text,
        re.IGNORECASE,
    )
    if not claimed:
        return VerificationResult(True, [], "No test count claim present.")
    claimed_num = int(claimed.group(1) or claimed.group(2) or claimed.group(3))

    records = [
        r for r in evidence_log.get_records()
        if getattr(r, "tool_name", getattr(r, "tool", "")) == "run_tests"
    ]
    if not records:
        return VerificationResult(
            False,
            [f"Claim of {claimed_num} tests without an actual recorded run"],
            "Fabricated",
        )

    last_out = getattr(records[-1], "raw_output", getattr(records[-1], "output_snippet", ""))
    actual = re.search(r"Ran\s+(\d+)\s+tests?", last_out, re.IGNORECASE)
    actual_num = int(actual.group(1)) if actual else -1

    if actual_num != claimed_num:
        return VerificationResult(
            False,
            [f"Claimed={claimed_num}, actual={actual_num}"],
            "Conflict",
        )
    return VerificationResult(True, [], "Match")


def check_git_push_claim(report_text: str, evidence_log: Any) -> VerificationResult:
    """Check claims regarding commit hash and push sync against actual documented git evidence."""
    claimed_hashes = re.findall(r"\b[0-9a-f]{7,40}\b", report_text)
    push_claimed = bool(re.search(r"push|origin/main", report_text, re.IGNORECASE))

    if not claimed_hashes and not push_claimed:
        return VerificationResult(True, [], "No git claim present.")

    records = [
        r for r in evidence_log.get_records()
        if getattr(r, "tool_name", getattr(r, "tool", "")) in ("git_show", "git_log", "git_diff", "git_push")
    ]
    if not records:
        return VerificationResult(
            False,
            ["Commit/push claim without any documented git_* call"],
            "Fabricated entirely.",
        )

    raw = "\n".join(getattr(r, "raw_output", getattr(r, "output_snippet", "")) for r in records)
    unsupported = [h for h in claimed_hashes if h[:7] not in raw]

    if unsupported:
        return VerificationResult(
            False,
            [f"Commit hash not found in evidence: {h}" for h in unsupported],
            "Conflict",
        )

    # push claim requires an empty git_diff record confirming HEAD vs origin sync
    if push_claimed:
        diff_records = [
            r for r in records
            if getattr(r, "tool_name", getattr(r, "tool", "")) == "git_diff"
        ]
        if not diff_records or getattr(diff_records[-1], "raw_output", getattr(diff_records[-1], "output_snippet", "")).strip() != "":
            return VerificationResult(
                False,
                ["Push claim without an empty git diff confirming sync"],
                "Unconfirmed",
            )

    return VerificationResult(True, [], "Match.")


def verify_report_strict(report_text: str, evidence_log: Any) -> VerificationResult:
    """Run all strict checks."""
    checks = [
        check_file_count_claim(report_text, evidence_log),
        check_commit_count_claim(report_text, evidence_log),
        check_test_count_claim(report_text, evidence_log),
        check_git_push_claim(report_text, evidence_log),
    ]
    all_unsupported = [c for check in checks for c in check.unsupported_claims]
    passed = all(check.passed for check in checks)
    return VerificationResult(
        passed=passed,
        unsupported_claims=all_unsupported,
        details="ok" if passed else f"{len(all_unsupported)} strict verification failure(s)."
    )


def gate_report(report_text: str, evidence_log: Any, retry_fn: Optional[Callable[..., str]] = None) -> str:
    """Gate before showing final report."""
    result = verify_report_strict(report_text, evidence_log)
    if result.passed:
        return report_text
    if retry_fn:
        return retry_fn(unsupported=result.unsupported_claims)
    return "⚠️ Verification failed:\n" + "\n".join(result.unsupported_claims)


# Deterministic disk-existence backstop for code-path claims.
# Path extensions considered "code artifacts" worth verifying on disk.
_PATH_CLAIM_RE = re.compile(r"[\w\-/\\]+\.(?:py|toml|md|json|yaml|yml|sh|cfg|ini|txt|go|js|ts|rs|java|cpp|c|h|rb)")
_VERSION_RE = re.compile(r"^\d+\.\d+")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def check_path_existence_claim(
    report_text: str,
    workspace_root: Optional[Path] = None,
    evidence_log: Any = None,
) -> VerificationResult:
    """Verify every claimed code path against disk existence + evidence.

    The existing ``verify_report`` checks path claims against evidence
    raw_outputs only — a hallucinated path that was never read by any tool is
    absent from outputs so it IS correctly flagged. However, a clever
    false-negative exists: a path appearing in a directory listing (e.g.
    ``ls core/`` shows adapters.py) would pass the substring check even if the
    agent never read the file's CONTENTS. This function adds a DISK CHECK
    (os.path.exists) for every ``*.py/.md/.toml/...`` path claim — the
    deterministic ground truth.

    Combined with ``verify_report``, both existence AND content-checking are
    sealed. NEVER uses an LLM — pure deterministic Python.

    Rule: a path that is on disk is accepted even if never read (real but
    unread → not a failure). A path NOT on disk AND not present in any evidence
    raw_output is a HARD FAILURE (the file cannot exist in the project).
    """
    if workspace_root is None:
        workspace_root = get_workspace_root()
    root = Path(workspace_root).resolve()

    # Collect evidence raw outputs once for the existing-check fallback.
    raw_outputs = ""
    if evidence_log is not None:
        try:
            records = evidence_log.get_records()
            raw_outputs = " ".join(
                getattr(r, "raw_output", getattr(r, "output_snippet", "")) for r in records
            )
        except Exception:
            raw_outputs = ""

    unsupported: List[str] = []

    for token in _PATH_CLAIM_RE.findall(report_text or ""):
        # Skip version strings (e.g. "1.2" from "python3 -c") and URLs.
        if _VERSION_RE.match(token) or _URL_RE.search(token):
            continue
        # Existing evidence check: if it literally appears in a tool output,
        # treat as supported (keeps the prior behavior intact).
        if raw_outputs and token in raw_outputs:
            continue
        # Resolve relative to the workspace root and check disk ground truth.
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            on_disk = candidate.exists()
        except OSError:
            on_disk = False
        if not on_disk and token not in raw_outputs:
            unsupported.append(f"Unsupported path (not on disk): {token}")

    passed = len(unsupported) == 0
    return VerificationResult(
        passed=passed,
        unsupported_claims=unsupported,
        details="All path claims exist on disk or in evidence." if passed
        else f"{len(unsupported)} path claim(s) not found on disk or in evidence.",
    )
