"""Evidence data model for verifiable agent outputs.

Every tool call gets a unique evidence_id (E-1, E-2, …).
EvidenceRecord is frozen — once created, never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set


# ── Supported evidence types ────────────────────────────────────────────────

EVIDENCE_TYPES: dict[str, str] = {
    "execute_shell":   "shell",
    "file_system":     "filesystem",
    "web_search":      "web",
    "search_memory":   "memory",
}


def _evidence_type(tool: str) -> str:
    return EVIDENCE_TYPES.get(tool, "other")


def _extract_subjects(tool: str, command_or_path: str) -> FrozenSet[str]:
    """Derive covered subjects from the tool invocation."""
    subjects: set[str] = set()
    for part in command_or_path.replace("/", " ").replace(".", " ").replace("_", " ").split():
        part = part.strip()
        if part and len(part) > 1 and not part.startswith("-"):
            subjects.add(part.lower())
    return frozenset(subjects)


# ── Core data types ─────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """A completed tool call — fully immutable after creation."""

    evidence_id: str            # "E-1", "E-2", …
    evidence_type: str          # "shell", "filesystem", "web", "memory"
    tool: str                   # "execute_shell", "file_system", …
    command_or_path: str        # brief summary of what was invoked
    success: bool               # if False, findings referencing this are rejected
    output_snippet: str         # first 200 chars of stdout/stderr
    covered_subjects: FrozenSet[str]  # extracted keywords from the command/path


@dataclass(frozen=True, slots=True)
class Finding:
    """A single factual claim traced to an evidence_id."""

    claim: str
    evidence_id: str            # must match an EvidenceRecord.evidence_id
    compatible_types: FrozenSet[str] = frozenset()  # e.g. {"filesystem", "shell"}


def _compute_confidence(findings: List[Finding],
                        records: Dict[str, EvidenceRecord]) -> float:
    """Derive confidence from evidence quantity and diversity.

    1 evidence   → 0.5
    2 evidences  → 0.8
    3+ differing types → 0.95
    """
    if not findings:
        return 0.0
    used_ids = {f.evidence_id for f in findings if f.evidence_id in records}
    if not used_ids:
        return 0.0
    types_used: set[str] = set()
    for eid in used_ids:
        types_used.add(records[eid].evidence_type)
    n = len(used_ids)
    if n == 1:
        return 0.5
    if n == 2:
        return 0.8
    # 3+ — check diversity
    if len(types_used) >= 2:
        return 0.95
    return 0.85


# ── Verifier Engine ─────────────────────────────────────────────────────────

class VerifierError(Exception):
    """Raised by the Verifier when an evidence check fails."""
    pass


class Verifier:
    """Independent verification stage. Runs after the LLM produces a report
    but before the result is published to the user.

    Checks:
      1. Every evidence_id exists.
      2. Every referenced EvidenceRecord.success == True.
      3. Each Finding's compatible_types match the record's evidence_type
         (if compatible_types is non-empty).
      4. At least one evidence record exists for substantive tasks.
    """

    @staticmethod
    def verify(
        findings: List[Finding],
        records: Dict[str, EvidenceRecord],
        require_tools: bool,
    ) -> None:
        """Raise VerifierError if any check fails."""
        if require_tools and not records:
            raise VerifierError(
                "Task aborted.\n\n"
                "Reason:\n"
                "Required workspace inspection was not completed.\n\n"
                "No verified evidence was collected.\n\n"
                "No report was generated."
            )

        for f in findings:
            if not f.evidence_id:
                raise VerifierError(
                    f"Finding '{f.claim[:60]}…' has empty evidence_id."
                )
            rec = records.get(f.evidence_id)
            if rec is None:
                raise VerifierError(
                    f"Finding '{f.claim[:60]}…' references "
                    f"missing evidence_id '{f.evidence_id}'."
                )
            if not rec.success:
                raise VerifierError(
                    f"Finding '{f.claim[:60]}…' references "
                    f"FAILED evidence {rec.evidence_id} "
                    f"({rec.tool}: {rec.command_or_path})."
                )
            if f.compatible_types and rec.evidence_type not in f.compatible_types:
                raise VerifierError(
                    f"Finding '{f.claim[:60]}…' expects type(s) "
                    f"{f.compatible_types} but evidence {rec.evidence_id} "
                    f"is type '{rec.evidence_type}'."
                )


# ── Evidence Log ────────────────────────────────────────────────────────────

class EvidenceLog:
    """Stores evidence records and findings. Thread-safe for reads."""

    def __init__(self) -> None:
        self._records: Dict[str, EvidenceRecord] = {}
        self._findings: List[Finding] = []
        self._counter: int = 0

    # ── record (write once) ─────────────────────────────────────────────

    def next_id(self) -> str:
        self._counter += 1
        return f"E-{self._counter}"

    def record(self, tool: str, command_or_path: str, success: bool,
               output_snippet: str) -> EvidenceRecord:
        eid = self.next_id()
        rec = EvidenceRecord(
            evidence_id=eid,
            evidence_type=_evidence_type(tool),
            tool=tool,
            command_or_path=command_or_path,
            success=success,
            output_snippet=output_snippet[:200],
            covered_subjects=_extract_subjects(tool, command_or_path),
        )
        self._records[eid] = rec
        return rec

    # ── queries ─────────────────────────────────────────────────────────

    def get(self, evidence_id: str) -> Optional[EvidenceRecord]:
        return self._records.get(evidence_id)

    @property
    def records(self) -> Dict[str, EvidenceRecord]:
        return dict(self._records)

    @property
    def findings(self) -> List[Finding]:
        return list(self._findings)

    def has_evidence(self) -> bool:
        return len(self._records) > 0

    # ── findings ────────────────────────────────────────────────────────

    def add_finding(self, claim: str, evidence_id: str,
                    compatible_types: Optional[Set[str]] = None) -> None:
        self._findings.append(Finding(
            claim=claim,
            evidence_id=evidence_id,
            compatible_types=frozenset(compatible_types) if compatible_types else frozenset(),
        ))

    def confidence(self) -> float:
        return _compute_confidence(self._findings, self._records)

    # ── formatted output ────────────────────────────────────────────────

    def summary_section(self) -> str:
        """Block appended showing evidence trace and confidence."""
        if not self._records:
            return "[No evidence collected]"
        lines = [""]
        for rec in self._records.values():
            mark = "✓" if rec.success else "✗"
            lines.append(
                f"  [{rec.evidence_id}] {mark} "
                f"{rec.tool}({rec.command_or_path})  "
                f"[{rec.evidence_type}]"
            )
        lines.append(f"  confidence: {self.confidence():.2f}")
        return "\n".join(lines)

    # ── batch verify ────────────────────────────────────────────────────

    def verify(self, require_tools: bool) -> None:
        """Run the Verifier against this log's findings and records."""
        Verifier.verify(
            findings=self._findings,
            records=self._records,
            require_tools=require_tools,
        )
