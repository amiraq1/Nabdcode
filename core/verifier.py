"""Independent, non-LLM deterministic verifier and rejection gate against fake success claims."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.parser import get_workspace_root


# ── Arabic normalization for matching (text is never modified, only search/capture) ──

_ARABIC_INDIC_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ARABIC_HAMZA_RE = re.compile(r"[إأآٱ]")


def _normalize_arabic_for_matching(text: str) -> str:
    """Normalize Arabic text for pattern matching only.

    - Arabic-Indic digits (٠-٩) → ASCII (0-9) BEFORE regex capture
    - Tatweel (ـ) removed
    - Hamza variants (إ/أ/آ/ٱ) → ا  (unified alef)
    """
    t = text.translate(_ARABIC_INDIC_TRANS)
    t = t.replace("ـ", "")
    t = _ARABIC_HAMZA_RE.sub("ا", t)
    return t

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


def check_final_answer_claim_gate(report_text: str, evidence_log: Any) -> VerificationResult:
    """Combined claim gate for final-answer emission.

    Checks (in order, all-or-nothing):
      1. "all tests passed" / "all N tests passed" with no pytest evidence → reject
      2. "Ran N tests" with wrong or missing pytest evidence → reject
      3. commit hash / push claims without git evidence → reject

    Does NOT check file path claims — those are handled by the separate
    ``check_path_existence_claim`` gate in ``_emit_final``.

    Returns a single ``VerificationResult`` with ALL unsupported claims listed,
    so the caller can present a complete rejection message and never produce
    a dual terminal outcome (the caller retries or hard-caps, never emits
    directly from this gate).

    Arabic patterns are normalized before matching (Indic digits → ASCII,
    hamza variants → alef, tatweel removed) and checked with the same
    strictness as English.
    """
    all_unsupported: list[str] = []
    _norm = _normalize_arabic_for_matching(report_text or "")

    _evidence_records = evidence_log.get_records() if evidence_log else []

    # ── Helper: records with "pass" or Arabic نجح/نجحت/تم in execute_shell/run_tests ──
    def _pytest_evidence_with_success() -> list:
        return [
            r for r in _evidence_records
            if getattr(r, "tool_name", getattr(r, "tool", "")) in ("execute_shell", "run_tests")
            and any(k in (getattr(r, "output_snippet", "") or "").lower()
                    for k in ("pass", "نجح", "تم"))
        ]

    # ── Helper: records with execute_shell/run_tests (any output) ──
    def _exec_evidence() -> list:
        return [
            r for r in _evidence_records
            if getattr(r, "tool_name", getattr(r, "tool", "")) in ("execute_shell", "run_tests")
        ]

    # ── Pattern E1: English "all tests passed" / "all N tests passed" ─────────
    _all_passed_re = re.compile(
        r"all\s+(\d+\s+)?tests?\s+passed",
        re.IGNORECASE,
    )
    _all_passed_match = _all_passed_re.search(report_text or "")
    if _all_passed_match:
        records = _pytest_evidence_with_success()
        if not records:
            count_hint = _all_passed_match.group(1)
            detail = f"Claimed '{_all_passed_match.group(0)}'"
            if count_hint:
                detail += f" ({count_hint.strip()} tests)"
            all_unsupported.append(
                f"{detail} without any execute_shell/run_tests "
                f"evidence with 'pass'/'نجح' in output"
            )

    # ── Pattern A1: Arabic "all tests passed" (جميع/كل الاختبارات نجحت) ─────
    _ar_all_passed_re = re.compile(
        r"(?:جميع|كل)\s+(?:ال)?اختبارات?\s+(?:نجحت|نجح|تمت|اجتيزت|مرت)"
        r"|(?:ال)?اختبارات?\s+(?:جميع|كل)\s+(?:نجحت|نجح|تمت|اجتيزت|مرت)"
        r"|نجحت\s+(?:جميع|كل)\s+(?:ال)?اختبارات?"
        r"|(?:نجح|نجحت|تمت)\s+(?:ال)?اختبارات?\s+(?:جميعها|كلها)",
    )
    _ar_all_passed_match = _ar_all_passed_re.search(_norm)
    if _ar_all_passed_match:
        if not _pytest_evidence_with_success():
            all_unsupported.append(
                "Arabic claim 'all tests passed' without any execute_shell/"
                "run_tests evidence with 'pass'/'نجح' in output"
            )

    # ── Pattern E2: English "Ran N tests" ──────────────────────────────────
    _ran_tests_re = re.compile(
        r"Ran\s+(\d+)\s+tests?",
        re.IGNORECASE,
    )
    _ran_match = _ran_tests_re.search(report_text or "")
    if _ran_match:
        claimed_count = int(_ran_match.group(1))
        records = _exec_evidence()
        if not records:
            all_unsupported.append(
                f"Claimed 'Ran {claimed_count} tests' with no "
                f"execute_shell/run_tests evidence record"
            )
        else:
            last_out = getattr(records[-1], "output_snippet", "") or ""
            _actual = re.search(r"Ran\s+(\d+)\s+tests?", last_out, re.IGNORECASE)
            actual_count = int(_actual.group(1)) if _actual else -1
            if actual_count != claimed_count:
                all_unsupported.append(
                    f"Claimed 'Ran {claimed_count} tests' but evidence "
                    f"shows {actual_count}"
                )

    # ── Pattern A2: Arabic count claims (عدد الاختبارات N / تم تشغيل N اختبار) ──
    _ar_count_re = re.compile(
        r"(?:عدد\s*(?:ال)?اختبارات?\s*(?::)?\s*(\d+))"
        r"|(?:عددها\s*(?::)?\s*(\d+))"
        r"|(?:تم\s+تشغيل\s+(\d+)\s+اختبار)",
    )
    _ar_count_match = _ar_count_re.search(_norm)
    if _ar_count_match:
        claimed_count = int((_ar_count_match.group(1) or _ar_count_match.group(2) or _ar_count_match.group(3)))
        records = _exec_evidence()
        if not records:
            all_unsupported.append(
                f"Arabic claim 'تم تشغيل {claimed_count} اختبار' with no "
                f"execute_shell/run_tests evidence record"
            )
        else:
            last_out = _normalize_arabic_for_matching(
                getattr(records[-1], "output_snippet", "") or ""
            )
            # Check both English and Arabic count patterns in normalized evidence
            _actual_en = re.search(r"Ran\s+(\d+)\s+tests?", last_out, re.IGNORECASE)
            _actual_ar = re.search(r"(?:عدد\s*(?:ال)?اختبارات?\s*(?::)?\s*(\d+))|(?:عددها\s*(?::)?\s*(\d+))|(?:تم\s+تشغيل\s+(\d+)\s*اختبار)", last_out)
            actual_count = -1
            if _actual_en:
                actual_count = int(_actual_en.group(1))
            elif _actual_ar:
                actual_count = int(_actual_ar.group(1) or _actual_ar.group(2) or _actual_ar.group(3))
            if actual_count != -1 and actual_count != claimed_count:
                all_unsupported.append(
                    f"Claimed '{claimed_count} tests' (Arabic) but evidence "
                    f"shows {actual_count}"
                )
            elif actual_count == -1:
                all_unsupported.append(
                    f"Arabic count claim '{claimed_count}' but no matching "
                    f"test-count found in evidence output"
                )

    # ── Pattern A3: Arabic "no errors" (لا توجد أخطاء) requires exec evidence ──
    _ar_no_errors_re = re.compile(
        r"لا\s+(?:يوجد|توجد|يوج)?\s*(?:اخطاء|فشل|خطا|مشاكل|فشلت)"
    )
    _ar_no_errors_match = _ar_no_errors_re.search(_norm)
    if _ar_no_errors_match:
        # Requires ANY execute_shell/run_tests evidence (not just file_system/read)
        if not _exec_evidence():
            all_unsupported.append(
                "Arabic 'no errors' claim without any execute_shell/run_tests "
                "evidence record"
            )

    # ── Pattern A4: Arabic commit/push ─────────────────────────────────────
    _ar_commit_re = re.compile(r"تم\s+(?:ال)?(?:ايداع|إيداع|إضافة|commit)\s*([a-f0-9]{7,})")
    _ar_commit_match = _ar_commit_re.search(_norm)
    if _ar_commit_match:
        _commit_result = check_git_push_claim(report_text or "", evidence_log)
        if not _commit_result.passed:
            all_unsupported.extend(_commit_result.unsupported_claims)

    _ar_push_re = re.compile(r"تم\s+(?:ال)?(?:رفع|push)\s*(?:إلى|ل(?:ـ)?)?\s*(?:origin|main|master|remote)?")
    _ar_push_match = _ar_push_re.search(_norm)
    if _ar_push_match:
        _push_result = check_git_push_claim(report_text or "", evidence_log)
        if not _push_result.passed:
            all_unsupported.extend(_push_result.unsupported_claims)

    # ── Pattern E3: English commit hash / push ─────────────────────────────
    _commit_result_en = check_git_push_claim(report_text or "", evidence_log)
    if not _commit_result_en.passed:
        all_unsupported.extend(_commit_result_en.unsupported_claims)

    passed = len(all_unsupported) == 0
    return VerificationResult(
        passed=passed,
        unsupported_claims=all_unsupported,
        details="ok" if passed
        else f"{len(all_unsupported)} unsupported claim(s): "
             f"{'; '.join(all_unsupported[:5])}"
             f"{'...' if len(all_unsupported) > 5 else ''}",
    )
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
