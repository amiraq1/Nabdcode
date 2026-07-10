"""Independent, non-LLM deterministic verifier and rejection gate against fake success claims."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


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
            unsupported.append(f"رقم غير مدعوم: {num}")

    # File paths
    for path in claims["file_paths"]:
        if path not in raw_outputs:
            unsupported.append(f"مسار غير مدعوم: {path}")

    # Commit hashes
    for h in claims["commit_hashes"]:
        if h not in raw_outputs:
            unsupported.append(f"commit hash غير مدعوم: {h}")

    passed = len(unsupported) == 0
    return VerificationResult(
        passed=passed,
        unsupported_claims=unsupported,
        details="كل الادعاءات مدعومة بأدلة." if passed else f"{len(unsupported)} ادعاء غير مدعوم.",
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
        return VerificationResult(True, [], "لا يوجد ادعاء عدّ ملفات.")

    claimed_num = int(claimed.group(1) or claimed.group(2))
    records = [
        r for r in evidence_log.get_records()
        if getattr(r, "tool_name", getattr(r, "tool", "")) in ("find_files", "list_files", "file_system", "execute_shell")
    ]

    if not records:
        return VerificationResult(
            False,
            [f"ادعاء 'عدد الملفات = {claimed_num}' بدون أي استدعاء find_files/list_files"],
            "لا يوجد دليل أداة يدعم هذا الادعاء إطلاقاً."
        )

    # Actual count = number of non-empty lines in the tool output
    actual_num = sum(
        len([line for line in getattr(r, "raw_output", getattr(r, "output_snippet", "")).strip().splitlines() if line.strip()])
        for r in records
    )

    if actual_num != claimed_num:
        return VerificationResult(
            False,
            [f"عدد مُدّعى={claimed_num} لكن العدّ الفعلي من evidence={actual_num}"],
            "تعارض عددي مباشر — تقرير مزيف."
        )
    return VerificationResult(True, [], f"العدد {claimed_num} مطابق للأداة الفعلية.")


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
                [f"{len(claimed)} رسائل commit مذكورة بدون أي استدعاء git_log"],
                "commits مُختلقة بالكامل — لا يوجد استدعاء git_log في evidence_log."
            )
        return VerificationResult(True, [], "لا يوجد ادعاء commits.")

    actual_output = "\n".join(getattr(r, "raw_output", getattr(r, "output_snippet", "")) for r in records)
    unsupported = [msg for msg in claimed if msg not in actual_output]

    if unsupported:
        return VerificationResult(
            False,
            [f"رسالة commit مُختلقة: '{m}'" for m in unsupported],
            f"{len(unsupported)} من {len(claimed)} رسائل commit غير موجودة في مخرجات git_log الفعلية."
        )
    return VerificationResult(True, [], "كل رسائل الـ commits مطابقة لـ git_log.")


def verify_report_strict(report_text: str, evidence_log: Any) -> VerificationResult:
    """Run all strict checks."""
    checks = [
        check_file_count_claim(report_text, evidence_log),
        check_commit_count_claim(report_text, evidence_log),
    ]
    all_unsupported = [c for check in checks for c in check.unsupported_claims]
    passed = all(check.passed for check in checks)
    return VerificationResult(
        passed=passed,
        unsupported_claims=all_unsupported,
        details="ok" if passed else f"{len(all_unsupported)} فشل تحقق صارم."
    )


def gate_report(report_text: str, evidence_log: Any, retry_fn: Optional[Callable[..., str]] = None) -> str:
    """Gate before showing final report."""
    result = verify_report_strict(report_text, evidence_log)
    if result.passed:
        return report_text
    if retry_fn:
        return retry_fn(unsupported=result.unsupported_claims)
    return "⚠️ فشل التحقق:\n" + "\n".join(result.unsupported_claims)
