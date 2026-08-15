"""Pre-Apply diff, risk, and test review for Nabdcode.

The reviewer is deliberately conservative: it consumes the existing pending-edit
queue, never executes a shell command, redacts likely secrets in previews, and
runs only repository-local pytest files selected from known paths.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.accept_edits_state import peek_pending

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s,;]+"
)
_HIGH_RISK_RE = re.compile(
    r"(?i)\b(shell|subprocess|exec|command|network|http|secret|token|password|"
    r"auth|credential|delete|remove|chmod|sudo|migration|database|deploy|push|workflow)\b"
)
_MEDIUM_RISK_RE = re.compile(
    r"(?i)\b(config|dependency|requirements|pyproject|package|schema|database|"
    r"permission|permission|file|write|refactor)\b"
)


def _redact(text: str, limit: int = 700) -> str:
    text = _SECRET_RE.sub(lambda m: m.group(1) + "=<redacted>", text or "")
    return text[:limit] + ("…" if len(text) > limit else "")


def _workspace(root: str | Path | None) -> Path:
    return Path(root or Path.cwd()).resolve()


def _candidate_tests(root: Path, files: list[str]) -> list[str]:
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return []
    candidates: list[Path] = []
    for file_path in files:
        stem = Path(file_path).stem.lower()
        for test in sorted(tests_dir.glob("test_*.py")):
            if stem and stem in test.stem.lower():
                candidates.append(test)
    unique: list[str] = []
    for path in candidates:
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        rel = str(resolved.relative_to(root))
        if rel not in unique:
            unique.append(rel)
    return unique[:8]


def build_review(state: Any, workspace_root: str | Path | None = None) -> dict[str, Any]:
    root = _workspace(workspace_root)
    plan_items = [str(item) for item in (getattr(state, "plan_items", ()) or ())]
    pending = peek_pending()
    files = [str(getattr(edit, "path", "")) for edit in pending if getattr(edit, "path", "")]
    diff_text = "\n".join(str(getattr(edit, "diff", "") or "") for edit in pending)
    risk_text = "\n".join(plan_items + files + [diff_text])
    additions = sum(int(getattr(edit, "additions", 0) or 0) for edit in pending)
    removals = sum(int(getattr(edit, "removals", 0) or 0) for edit in pending)
    if _HIGH_RISK_RE.search(risk_text) or additions > 100 or removals > 100:
        risk = "high"
    elif _MEDIUM_RISK_RE.search(risk_text) or len(files) > 3 or additions > 30 or removals > 30:
        risk = "medium"
    else:
        risk = "low"

    edit_previews = []
    for edit in pending:
        edit_previews.append(
            {
                "path": str(getattr(edit, "path", "")),
                "additions": int(getattr(edit, "additions", 0) or 0),
                "removals": int(getattr(edit, "removals", 0) or 0),
                "diff_preview": _redact(str(getattr(edit, "diff", "") or "")),
            }
        )
    tests = _candidate_tests(root, files)
    return {
        "revision": int(getattr(state, "plan_revision", 0) or 0),
        "risk": risk,
        "plan_items": plan_items,
        "files": files,
        "pending_edits": edit_previews,
        "additions": additions,
        "removals": removals,
        "test_candidates": tests,
        "test_status": "not_run" if tests else "not_applicable",
        "test_output": "",
    }


def run_review_tests(report: dict[str, Any], workspace_root: str | Path | None = None) -> dict[str, Any]:
    root = _workspace(workspace_root)
    tests = [str(item) for item in report.get("test_candidates", [])]
    if not tests:
        report["test_status"] = "not_applicable"
        return report
    env = os.environ.copy()
    env["NABD_NONINTERACTIVE"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *tests],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        report["test_status"] = "passed" if result.returncode == 0 else "failed"
        report["test_output"] = _redact((result.stdout or "") + (result.stderr or ""), 1800)
    except subprocess.TimeoutExpired:
        report["test_status"] = "timeout"
        report["test_output"] = "Review tests exceeded the 120 second limit."
    except OSError as exc:
        report["test_status"] = "error"
        report["test_output"] = str(exc)
    return report


def review_is_approved(state: Any) -> bool:
    revision = int(getattr(state, "plan_revision", 0) or 0)
    return (
        revision > 0
        and int(getattr(state, "review_approved_revision", 0) or 0) == revision
        and str(getattr(state, "review_test_status", "")) in {"passed", "not_applicable"}
    )


def store_review(state: Any, report: dict[str, Any]) -> None:
    state.review_revision = int(report.get("revision", 0) or 0)
    state.review_report = dict(report)
    state.review_test_status = str(report.get("test_status", "not_run"))
    state.review_approved_revision = 0


def approve_review(state: Any) -> tuple[bool, str]:
    revision = int(getattr(state, "plan_revision", 0) or 0)
    report = dict(getattr(state, "review_report", {}) or {})
    if int(report.get("revision", 0) or 0) != revision or int(getattr(state, "review_revision", 0) or 0) != revision:
        return False, "No current review exists. Run `/review` first."
    status = str(report.get("test_status", "not_run"))
    if status not in {"passed", "not_applicable"}:
        return False, f"Review cannot be approved while tests are {status}. Run `/review run` after fixing the issue."
    state.review_approved_revision = revision
    state.review_test_status = status
    state.plan_audit.append({"event": "review_approved", "revision": revision, "risk": report.get("risk", "unknown")})
    return True, f"Review approved for plan revision {revision} (risk={report.get('risk', 'unknown')})."


def format_review(report: dict[str, Any]) -> str:
    lines = [
        f"[Review] revision={report.get('revision', 0)} risk={report.get('risk', 'unknown')} ",
        f"files={len(report.get('files', []))} +{report.get('additions', 0)}/-{report.get('removals', 0)}",
        "Plan:",
    ]
    lines.extend(f"  {i}. {item}" for i, item in enumerate(report.get("plan_items", []), 1))
    if not report.get("plan_items"):
        lines.append("  (no recorded plan)")
    lines.append(f"Tests: {report.get('test_status', 'not_run')} — {', '.join(report.get('test_candidates', [])) or 'none'}")
    for edit in report.get("pending_edits", []):
        lines.append(f"Diff: {edit['path']} (+{edit['additions']}/-{edit['removals']})")
        if edit.get("diff_preview"):
            lines.append(edit["diff_preview"])
    if report.get("test_output"):
        lines.append(f"Test output:\n{report['test_output']}")
    return "\n".join(lines)
