"""tests/test_provenance.py — foreign authorship must not enter this history."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN = ("commandcode", "noreply@commandcode.ai", "commandcodebot")

REPO = Path(__file__).resolve().parents[1]
QUARANTINE = REPO / "docs" / "provenance_quarantine.txt"

# Pinned so the declared debt cannot grow in silence. Update only with an
# explicit written decision recorded in the quarantine file itself.
# 2026-08-07: 24 → 26 — human decision (Am+8): recorded 478766d + e9c447e,
# 2026-08-15: 26 → 27 — human decision: recorded historical commit 5b743e8
# 2026-08-16: 27 → 28 — human decision: recorded historical commit d0e28f8
# assistant commits that carried the wrapper trailer before repo policy was
# enforced. Quarantine file documents the decision.
QUARANTINE_SIZE = 28

ATTRIBUTION_CORRECTIONS = REPO / "docs" / "attribution_corrections.txt"
_ATTRIBUTION_RECORD_RE = re.compile(r"^[0-9a-f]{7,40}\s*->\s*[0-9a-f]{7,40}")


def _find_forbidden(text: str) -> list[str]:
    low = text.lower()
    return sorted({token for token in FORBIDDEN if token in low})


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(cwd) if cwd else None,
    ).stdout


def _quarantined() -> set[str]:
    """Recorded debt. Entries may be abbreviated or full SHAs."""
    if not QUARANTINE.exists():
        return set()
    entries: set[str] = set()
    for line in QUARANTINE.read_text(encoding="utf-8").splitlines():
        sha = line.split("#", 1)[0].strip().lower()
        if sha:
            entries.add(sha)
    return entries


def _is_quarantined(sha: str, known: set[str]) -> bool:
    """Match on prefix: git guarantees abbreviations are unambiguous."""
    low = sha.lower()
    return any(low.startswith(entry) for entry in known)


def _quarantine_records() -> list[tuple[str, str]]:
    """Return declared-debt entries and their required human-readable reasons."""
    records: list[tuple[str, str]] = []
    for line in QUARANTINE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        sha, separator, reason = stripped.partition("#")
        records.append((sha.strip().lower(), reason.strip() if separator else ""))
    return records


def _contaminated(cwd: Path | None = None) -> dict[str, list[str]]:
    """Every reachable commit whose message carries foreign provenance.

    Keys are FULL SHAs. Never compare truncated identifiers of differing
    widths — that silently classifies known commits as unknown.
    """
    raw = _git("log", "--all", "--format=%H%x1f%B%x1e", cwd=cwd)
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


def test_head_commit_is_clean():
    """Unconditional. No range, no baseline, no escape."""
    body = _git("log", "-1", "--format=%B")
    hits = _find_forbidden(body)
    assert not hits, f"HEAD carries foreign provenance: {hits}"


def test_no_foreign_provenance_outside_quarantine() -> None:
    """Scans ALL reachable history, not a range that launders via main."""
    known = _quarantined()
    unknown = {
        sha: hits
        for sha, hits in _contaminated().items()
        if not _is_quarantined(sha, known)
    }
    assert not unknown, (
        "foreign provenance in commits not listed in "
        f"{QUARANTINE.relative_to(REPO)}:\n"
        + "\n".join(
            f"  {sha[:12]}: {', '.join(hits)}"
            for sha, hits in sorted(unknown.items())
        )
    )


def test_quarantine_records_are_unique_documented_and_nonambiguous() -> None:
    """Declared debt is documented and unambiguous, including in shallow clones."""
    records = _quarantine_records()
    entries = [sha for sha, _reason in records]
    assert len(entries) == len(set(entries)), "quarantine contains duplicate commit prefixes"
    assert all(re.fullmatch(r"[0-9a-f]{7,40}", sha) for sha in entries)
    assert all(reason for _sha, reason in records), "every quarantine entry needs a reason"

    # A development or CI checkout may be shallow, so historical debt can be
    # unavailable locally. When a matching reachable commit exists, its prefix
    # must still be unambiguous; otherwise the exact documented record remains
    # the audit reference and the no-new-contamination guards continue to run.
    contaminated = _contaminated()
    for entry in entries:
        matches = [sha for sha in contaminated if sha.startswith(entry)]
        assert len(matches) <= 1, f"quarantine entry {entry} is ambiguous"


def test_quarantine_does_not_grow_silently():
    """Declared debt is fixed in size until a human decides otherwise."""
    actual = len(_quarantined())
    assert actual == QUARANTINE_SIZE, (
        f"quarantine size changed: expected {QUARANTINE_SIZE}, found {actual}. "
        "Growing it requires an explicit recorded decision."
    )


def test_guard_detects_contamination_in_a_real_repository(tmp_path):
    """Real falsification: a real commit, in a real repo, must be caught."""
    repo = tmp_path / "probe"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "probe@example.invalid", cwd=repo)
    _git("config", "user.name", "Probe", cwd=repo)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git("add", "f.txt", cwd=repo)
    _git(
        "commit",
        "-q",
        "-m",
        "probe: seeded violation\n\n"
        "Co-authored-by: CommandCodeBot noreply@commandcode.ai",
        cwd=repo,
    )
    found = _contaminated(cwd=repo)
    assert found, "detector failed to catch a real contaminated commit"


def _attribution_corrections() -> list[str]:
    """Data records only; '#' header lines are documentation, not records."""
    if not ATTRIBUTION_CORRECTIONS.exists():
        return []
    return [
        line
        for line in ATTRIBUTION_CORRECTIONS.read_text(encoding="utf-8").splitlines()
        if _ATTRIBUTION_RECORD_RE.match(line)
    ]


def test_attribution_corrections_count_is_fixed() -> None:
    """Recorded corrections are decisions; the count must stay exactly one."""
    records = _attribution_corrections()
    assert len(records) == 1, (
        f"{ATTRIBUTION_CORRECTIONS.relative_to(REPO)} data-record count changed:\n"
        + "\n".join(f"  {r}" for r in records)
    )
