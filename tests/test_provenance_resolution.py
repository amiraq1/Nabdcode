"""Guard: provenance resolution — quarantine stays complete, HEAD stays clean.

After the Am+8 human decision (2026-08-07):
  - 478766d and e9c447e are recorded as DECLARED DEBT in the quarantine file
    (they carried the assistant wrapper's Co-authored-by trailer before repo
    policy was enforced on assistant commits).
  - QUARANTINE_SIZE was raised 24 → 26 to match.
  - Going forward, assistant commits are made WITHOUT the trailer, so HEAD
    must never carry foreign provenance and the quarantine must cover every
    contaminated commit reachable in history.

This guard re-implements the two provenance invariants so they cannot silently
regress, without depending on test ordering.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN = ("commandcode", "noreply@commandcode.ai", "commandcodebot")

REPO = Path(__file__).resolve().parents[1]
QUARANTINE = REPO / "docs" / "provenance_quarantine.txt"


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(cwd) if cwd else None,
    ).stdout


def _find_forbidden(text: str) -> list[str]:
    low = text.lower()
    return sorted({token for token in FORBIDDEN if token in low})


def _quarantined() -> set[str]:
    if not QUARANTINE.exists():
        return set()
    entries: set[str] = set()
    for line in QUARANTINE.read_text(encoding="utf-8").splitlines():
        sha = line.split("#", 1)[0].strip().lower()
        if sha:
            entries.add(sha)
    return entries


def _is_quarantined(sha: str, known: set[str]) -> bool:
    low = sha.lower()
    return any(low.startswith(entry) for entry in known)


def _contaminated() -> dict[str, list[str]]:
    raw = _git("log", "--all", "--format=%H%x1f%B%x1e")
    found: dict[str, list[str]] = {}
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, body = record.partition("\x1f")
        sha = sha.strip().lower()
        hits = _find_forbidden(body)
        if sha and hits:
            found[sha] = hits
    return found


def test_quarantine_covers_every_contaminated_commit():
    """Every reachable contaminated commit must be recorded as declared debt."""
    known = _quarantined()
    unknown = {
        sha: hits
        for sha, hits in _contaminated().items()
        if not _is_quarantined(sha, known)
    }
    assert not unknown, (
        "contaminated commits not in quarantine:\n"
        + "\n".join(f"  {sha[:12]}: {', '.join(hits)}" for sha, hits in sorted(unknown.items()))
    )


def test_head_commit_has_no_foreign_provenance():
    """Unconditional: HEAD must never carry the assistant trailer again."""
    body = _git("log", "-1", "--format=%B")
    hits = _find_forbidden(body)
    assert not hits, f"HEAD carries foreign provenance: {hits}"
