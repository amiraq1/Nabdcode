"""Persistent repository context tracking (STATE.md / LESSONS.md).

Gives NABD OS a project-level memory layer: a scannable task-state log and a
curated failure-prevention ledger. All writes are best-effort and guarded so
a missing/!writable file can never crash the orchestrator.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any, Dict, Optional

from core.parser import get_workspace_root


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _task_id_for(task: str) -> str:
    """Derive a stable, filesystem-safe task id from the task text."""
    digest = abs(hash(task)) % 100000
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower())[:40].strip("-")
    return f"{slug or 'task'}-{digest}"


class RepositoryContextManager:
    """Maintains STATE.md (task log) and LESSONS.md (failure ledger)."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else get_workspace_root()

    # ── Public API ───────────────────────────────────────────────────────
    def update_state(self, task_id: str, status: str, payload: Dict[str, Any]) -> None:
        """Append a scannable entry to STATE.md under its status section.

        The entry is MOVED (not duplicated): any prior line carrying the same
        task_id is stripped first, so a two-call lifecycle (In Progress ->
        Completed) relocates the item to the new section instead of leaving a
        stale copy behind.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / "STATE.md"
            line = self._format_state_line(task_id, status, payload)
            raw = path.read_text(encoding="utf-8") if path.exists() else ""
            if not raw:
                raw = self._state_header()
            raw = self._remove_task_id(raw, task_id)
            raw = self._insert_under_section(raw, status, line)
            path.write_text(raw, encoding="utf-8")
        except Exception:
            # Never let context tracking crash the orchestrator.
            pass

    def record_lesson(
        self,
        task_id: str,
        failed_code: str,
        traceback_str: str,
        fix_applied: str,
    ) -> None:
        """Append a concrete failure-mode + prevention rule to LESSONS.md."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / "LESSONS.md"
            entry = self._format_lesson(task_id, failed_code, traceback_str, fix_applied)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if not existing:
                existing = self._lessons_header()
            existing = existing.rstrip() + "\n" + entry + "\n"
            path.write_text(existing, encoding="utf-8")
        except Exception:
            pass

    # ── Formatting helpers ───────────────────────────────────────────────
    @staticmethod
    def _format_state_line(task_id: str, status: str, payload: Dict[str, Any]) -> str:
        status = (status or "unknown").strip()
        ts = _now()
        extra = ""
        if isinstance(payload, dict):
            bits = []
            for k in ("attempts", "stage", "reason", "error"):
                if k in payload and payload[k] is not None:
                    bits.append(f"{k}={payload[k]}")
            if bits:
                extra = " — " + ", ".join(bits)
        return f"- **{status}** | `{task_id}` | {ts}{extra}"

    @staticmethod
    def _format_lesson(
        task_id: str,
        failed_code: str,
        traceback_str: str,
        fix_applied: str,
    ) -> str:
        date = _now().split(" ")[0]
        # Failure Mode: extract the exception type + first offending line.
        exc_type = "Unknown"
        m = re.search(r"(\w+(?:Error|Exception|Warning))", traceback_str or "")
        if m:
            exc_type = m.group(1)
        failure_mode = exc_type
        # Prevention Rule: derive a concrete guard from the fix, if present.
        if fix_applied and fix_applied.strip():
            prevention = f"Applied fix: {fix_applied.strip()}"
        else:
            prevention = "No fix recorded — review and add a regression guard."
        return (
            f"### {date} — `{task_id}`\n"
            f"- **Failure Mode:** {failure_mode}\n"
            f"- **Prevention Rule:** {prevention}\n"
        )

    @staticmethod
    def _state_header() -> str:
        return (
            "# Task State Log\n\n"
            "## In Progress\n"
            "## Completed\n"
            "## Escalated to Human\n"
        )

    @staticmethod
    def _remove_task_id(existing: str, task_id: str) -> str:
        """Drop any existing STATE.md line that references ``task_id``.

        Lines embed the id as a backticked token (`` `task-id` ``); matching on
        that token guarantees we strip the prior lifecycle entry (e.g. the
        "In Progress" copy) without touching unrelated lines.
        """
        needle = f"`{task_id}`"
        kept = [
            ln for ln in existing.splitlines()
            if needle not in ln
        ]
        return "\n".join(kept).rstrip() + "\n"

    @staticmethod
    def _insert_under_section(existing: str, status: str, line: str) -> str:
        """Insert ``line`` directly beneath the matching '## status' heading."""
        heading = f"## {status}"
        lines = existing.splitlines()
        out = []
        inserted = False
        for i, ln in enumerate(lines):
            out.append(ln)
            if not inserted and ln.strip() == heading:
                # Insert after this heading (and any blank line following it).
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    out.append(lines[j])
                    j += 1
                out.append(line)
                inserted = True
        if not inserted:
            # Unknown status: append a new section at the end.
            out.append("")
            out.append(heading)
            out.append(line)
        # Ensure trailing newline.
        text = "\n".join(out).rstrip() + "\n"
        return text

    @staticmethod
    def _lessons_header() -> str:
        return "# Lessons Learned\n\n"

    # ── Convenience for orchestrator use ─────────────────────────────────
    @staticmethod
    def task_id_for(task: str) -> str:
        return _task_id_for(task)
