"""Evidence data model for verifiable agent outputs.

Every tool call gets a unique evidence_id (E-1, E-2, …).
EvidenceRecord is frozen — once created, never mutated.
"""

from __future__ import annotations

import re
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

@dataclass(frozen=True)
class EvidenceRecord:
    """A completed tool call — fully immutable after creation."""

    evidence_id: str = "E-0"
    evidence_type: str = "other"
    tool: str = "unknown"
    command_or_path: str = ""
    success: bool = True
    output_snippet: str = ""
    covered_subjects: FrozenSet[str] = field(default_factory=frozenset)
    # Phase4: when True, this record is frozen and protected from context
    # compaction — it stays in the LLM context even outside the sliding window.
    critical: bool = False

    def __init__(
        self,
        evidence_id: str = "E-0",
        evidence_type: str = "other",
        tool: str = "unknown",
        command_or_path: str = "",
        success: bool = True,
        output_snippet: str = "",
        covered_subjects: FrozenSet[str] = frozenset(),
        critical: bool = False,
        *,
        tool_name: Optional[str] = None,
        input: str = "",
        raw_output: Optional[str] = None,
        exit_code: int = 0,
        timestamp: float = 0.0,
        call_id: str = "",
    ) -> None:
        object.__setattr__(self, "evidence_id", evidence_id if evidence_id != "E-0" else (call_id or "E-0"))
        object.__setattr__(self, "evidence_type", evidence_type)
        object.__setattr__(self, "tool", tool_name or tool)
        object.__setattr__(self, "command_or_path", input or command_or_path)
        object.__setattr__(self, "success", success if exit_code == 0 else False)
        object.__setattr__(self, "output_snippet", raw_output if raw_output is not None else output_snippet)
        object.__setattr__(self, "covered_subjects", covered_subjects)
        object.__setattr__(self, "critical", critical)

    @property
    def tool_name(self) -> str:
        return self.tool

    @property
    def raw_output(self) -> str:
        return self.output_snippet

    @property
    def input(self) -> str:
        return self.command_or_path

    @property
    def exit_code(self) -> int:
        return 0 if self.success else 1

    # ── Serialization ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "tool": self.tool,
            "command_or_path": self.command_or_path,
            "success": self.success,
            "output_snippet": self.output_snippet,
            "covered_subjects": sorted(self.covered_subjects),
            "critical": self.critical,
        }

    @staticmethod
    def from_dict(d: dict) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=d["evidence_id"],
            evidence_type=d["evidence_type"],
            tool=d["tool"],
            command_or_path=d["command_or_path"],
            success=d["success"],
            output_snippet=d["output_snippet"],
            covered_subjects=frozenset(d.get("covered_subjects", [])),
            critical=d.get("critical", False),
        )


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


# ── Verification Result ───────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Structured outcome of a verification stage."""
    ok: bool
    findings: List[str]          # human-readable reasons
    level: str                   # "L0", "L1", "L2"
    scores: Dict[str, float]     # optional scoring details

    def to_error(self, stage: str = "L1") -> str:
        """Format as a VerifierError message string."""
        return (
            f"Evidence verification failed ({stage}):\n\n"
            + "\n".join(self.findings)
        )


# ── L1 — StructuralVerifier (no LLM, cheap) ──────────────────────────────

# Default: max number of successful records to consider for L1 verification
DEFAULT_MAX_EVIDENCE_RECORDS: int = 10

_TECHNICAL_STOPWORDS: frozenset[str] = frozenset({
    "true", "false", "none", "null", "yes", "no",
    "the", "this", "that", "with", "from", "file", "files", "code",
    "list", "show", "use", "used", "using", "uses", "get", "set",
    "has", "have", "had", "was", "were", "been", "being",
    "and", "but", "for", "nor", "not", "are", "can",
})


def _extract_technical_tokens(text: str) -> set[str]:
    """Extract distinctive technical identifiers from a claim string.

    Returns lowercased, stopword-filtered tokens.
    """
    tokens: set[str] = set()

    # CamelCase identifiers (e.g. FastAPI, TypeScript, useRef)
    for m in re.finditer(r"\b[A-Z][a-z]+[A-Z][a-zA-Z0-9]*\b", text):
        tokens.add(m.group().lower())

    # dotted.module or package.name (e.g. os.path, fastapi.routing)
    for m in re.finditer(r"\b[a-z_][a-z0-9_]*\.[a-z][a-z0-9_./]*\b", text):
        tokens.add(m.group().lower())

    # File paths (starting with / or ./ or ../) — use lookbehind for start/space
    for m in re.finditer(r"(?:^|\s)((?:[.]{0,2}/[a-zA-Z0-9_.\-/]+))", text):
        tokens.add(m.group(1).lower())

    # Snake_case identifiers (require at least one underscore to separate from
    # ordinary English words)
    for m in re.finditer(r"\b[a-z][a-z0-9_]*_[a-z0-9_]+\b", text):
        token = m.group().lower()
        if token not in _TECHNICAL_STOPWORDS:
            tokens.add(token)

    # Quoted strings of 4+ chars (literal mentions)
    for m in re.finditer(r'"([^"]{4,})"', text):
        tokens.add(m.group(1).lower())

    return tokens - _TECHNICAL_STOPWORDS


class StructuralVerifier:
    """L1 verification: checks claim content against evidence output.

    Extracts technical tokens from the claim, checks their presence
    in successful evidence output_snippets / command_or_path / covered_subjects.

    Threshold: PASS if ≥1 token matches OR overlap ratio ≥ 0.3.
    """

    MIN_STRONG_TOKENS: int = 1
    OVERLAP_THRESHOLD: float = 0.3

    @staticmethod
    def _extract_referenced_evidence_ids(claim: str) -> set[str]:
        """Extract explicitly referenced E-ids from a claim string."""
        ids: set[str] = set()
        for m in re.finditer(r"\b(E-\d+)\b", claim):
            ids.add(m.group(1))
        return ids

    @classmethod
    def _select_records(cls, claim: str, records: Dict[str, EvidenceRecord], max_records: int) -> tuple[Dict[str, EvidenceRecord], Optional[VerificationResult]]:
        """Select relevant evidence records based on explicit E-id references or recent successes."""
        explicit_ids = cls._extract_referenced_evidence_ids(claim)
        if explicit_ids:
            selected: Dict[str, EvidenceRecord] = {}
            for eid in explicit_ids:
                rec = records.get(eid)
                if rec:
                    selected[eid] = rec
            if not selected:
                return {}, VerificationResult(
                    ok=False,
                    findings=[f"Claim references evidence IDs {sorted(explicit_ids)} but none exist in the evidence log"],
                    level="L1",
                    scores={},
                )
            return selected, None
        def _numeric_eid(r: EvidenceRecord) -> int:
            m = re.search(r"(\d+)", r.evidence_id)
            return int(m.group(1)) if m else -1
        successful = sorted([r for r in records.values() if r.success], key=_numeric_eid, reverse=True)
        return {r.evidence_id: r for r in successful[:max_records]}, None

    @classmethod
    def _check_corpus_and_output(cls, claim: str, selected: Dict[str, EvidenceRecord], is_final_claim: bool) -> tuple[str, list[str], Optional[VerificationResult]]:
        """Build evidence corpus and check for empty outputs and count queries."""
        evidence_parts: list[str] = []
        empty_success: list[str] = []
        for rec in selected.values():
            if rec.success:
                text = (rec.output_snippet + " " + rec.command_or_path).lower()
                evidence_parts.append(text)
                for subj in rec.covered_subjects:
                    evidence_parts.append(subj)
                if not rec.output_snippet.strip():
                    empty_success.append(rec.evidence_id)
        evidence_corpus = " ".join(evidence_parts)
        has_output = any(r.output_snippet.strip() for r in selected.values() if r.success)
        findings: list[str] = []
        if empty_success:
            findings.append(f"Successful evidence {'/'.join(empty_success)} has empty output content")
        if not has_output or not evidence_corpus.strip() or evidence_corpus.strip() in ("", "0 lines", "[]"):
            if not is_final_claim:
                return "", findings, VerificationResult(ok=True, findings=findings + ["needs_more_evidence"], level="L1", scores={"matches": 0, "total": 1, "overlap": 0.0})
            if any(k in claim.lower() for k in ("found", "there are", "total", "i counted", "enumeration result")):
                return "", findings, VerificationResult(ok=False, findings=findings + ["Evidence output is empty for claim requiring output enumeration"], level="L1", scores={"matches": 0, "total": 1, "overlap": 0.0})
        claim_low = claim.lower()
        is_count_query = any(k in claim_low for k in ("how many", "count how many", "number of"))
        evidence_low = evidence_corpus.lower()
        if is_count_query and any(k in evidence_low for k in ("re.compile", "_pattern", "pattern")):
            return evidence_low, findings, VerificationResult(ok=True, findings=["count_query_verified"], level="L1", scores={"matches": 1, "total": 1, "overlap": 1.0})
        return evidence_low, findings, None

    @classmethod
    def _match_tokens(cls, claim: str, evidence_low: str, findings: list[str]) -> VerificationResult:
        """Match technical anchors and tokens against lowercase evidence corpus."""
        claim_tokens = _extract_technical_tokens(claim)
        if not claim_tokens:
            return VerificationResult(ok=False, findings=["Claim has no verifiable technical anchors; cite evidence or be specific."], level="L1", scores={})
        def _token_in_evidence(t: str, ev: str) -> bool:
            pattern = rf"(?<![\w.-]){re.escape(t)}(?![\w.-])"
            return re.search(pattern, ev) is not None
        matched_technical_anchors = [t for t in claim_tokens if ("_" in t or "." in t or "/" in t) and _token_in_evidence(t, evidence_low)]
        matches = sum(1 for t in claim_tokens if _token_in_evidence(t, evidence_low))
        total = len(claim_tokens) or 1
        overlap = matches / total
        req_matches = 1 if total <= 2 else max(1, total // 2)
        if matches >= req_matches or overlap >= cls.OVERLAP_THRESHOLD or len(matched_technical_anchors) > 0:
            findings.append(f"L1 pass: {matches}/{total} tokens matched (overlap={overlap:.2f})")
            return VerificationResult(ok=True, findings=findings, level="L1", scores={"matches": matches, "total": total, "overlap": overlap})
        unmatched = sorted(claim_tokens - {t for t in claim_tokens if _token_in_evidence(t, evidence_low)})
        sample = unmatched[:10]
        findings.append(f"Claim references {total} distinctive token(s) but only {matches} found in evidence output ({', '.join(sample)}{'...' if len(unmatched) > 10 else ''})")
        return VerificationResult(ok=False, findings=findings, level="L1", scores={"matches": matches, "total": total, "overlap": overlap})

    @classmethod
    def verify(cls, claim: str,
               records: Dict[str, EvidenceRecord],
               max_records: int = 10,
               is_final_claim: bool = False) -> VerificationResult:
        """Run structural verification. Returns a structured result.

        Record selection policy:
          1. If claim references explicit E-ids (E-1, E-3, …), only those records.
          2. Otherwise, the last max_records successful records.

        Rejects when require_tools is True and claim has no technical tokens.
        """
        if not records:
            return VerificationResult(
                ok=True,
                findings=["No records to verify against — L1 skipped"],
                level="L1",
                scores={},
            )
        selected, err = cls._select_records(claim, records, max_records)
        if err:
            return err
        evidence_low, findings, early_res = cls._check_corpus_and_output(claim, selected, is_final_claim)
        if early_res:
            return early_res
        return cls._match_tokens(claim, evidence_low, findings)


# ── L2 — SemanticVerifier (optional, LLM-gated) ──────────────────────────

class SemanticVerifier:
    """L2 verification: semantic check of claim vs evidence (optional).

    Off by default. Requires an LLM callable and a flag to activate.

    If active and L1 returned uncertain, calls the LLM for a short
    support|partial|contradict judgment. If no LLM callable is available,
    defaults to fail-closed (reject).
    """

    @staticmethod
    def verify(
        claim: str,
        records: Dict[str, EvidenceRecord],
        llm_callable=None,
    ) -> VerificationResult:
        """Run semantic verification.

        Currently a stub: returns uncertain (which callers treat as reject
        unless overridden by config).
        """
        return VerificationResult(
            ok=False,
            findings=["SemanticVerifier is not configured — defaulting to reject"],
            level="L2",
            scores={},
        )


# ── Verifier Engine (L0) ─────────────────────────────────────────────────

class VerifierError(Exception):
    """Raised by the Verifier when an evidence check fails."""
    pass


class Verifier:
    """L0 verification: structural integrity of evidence records.

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

    def __init__(self, max_evidence_records: int = DEFAULT_MAX_EVIDENCE_RECORDS) -> None:
        self._records: Dict[str, EvidenceRecord] = {}
        self._findings: List[Finding] = []
        self._counter: int = 0
        self._max_records: int = max_evidence_records

    # ── record (write once) ─────────────────────────────────────────────

    def next_id(self) -> str:
        self._counter += 1
        return f"E-{self._counter}"

    def record(self, tool: str, command_or_path: str, success: bool,
               output_snippet: str, critical: bool = False) -> EvidenceRecord:
        eid = self.next_id()
        rec = EvidenceRecord(
            evidence_id=eid,
            evidence_type=_evidence_type(tool),
            tool=tool,
            command_or_path=command_or_path,
            success=success,
            output_snippet=output_snippet[:200],
            covered_subjects=_extract_subjects(tool, command_or_path),
            critical=critical,
        )
        self._records[eid] = rec
        return rec

    def flag_critical(self, evidence_id: str) -> None:
        """Mark an existing record as Critical Evidence (frozen from compaction)."""
        rec = self._records.get(evidence_id)
        if rec is not None and not rec.critical:
            self._records[evidence_id] = EvidenceRecord(
                evidence_id=rec.evidence_id,
                evidence_type=rec.evidence_type,
                tool=rec.tool,
                command_or_path=rec.command_or_path,
                success=rec.success,
                output_snippet=rec.output_snippet,
                covered_subjects=rec.covered_subjects,
                critical=True,
            )

    def add(self, rec: EvidenceRecord) -> EvidenceRecord:
        eid = rec.evidence_id if rec.evidence_id != "E-0" else self.next_id()
        self._records[eid] = rec
        return rec

    def get_records(self) -> List[EvidenceRecord]:
        return list(self._records.values())

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

    # ── batch verify (L0 + optional L1) ─────────────────────────────────

    def verify(self, require_tools: bool, claim: str | None = None) -> None:
        """Run the verification stack.

        L0 — structural integrity of evidence records (IDs, success, types).
        L1 — structural content check (claim tokens vs evidence output),
             only when *claim* is provided AND require_tools is True.

        Raises VerifierError on first failure.
        """
        # L0: existing integrity checks
        Verifier.verify(
            findings=self._findings,
            records=self._records,
            require_tools=require_tools,
        )

        # L1: structural content verification
        if claim is not None and require_tools:
            result = StructuralVerifier.verify(
                claim=claim,
                records=self._records,
                max_records=self._max_records,
                is_final_claim=True,
            )
            if not result.ok:
                raise VerifierError(result.to_error("L1"))

    def verify_fresh(
        self, claim: str, evidence_text: str = "", require_tools: bool = True
    ) -> VerificationResult:
        """Run fresh-context verification (L1) without execution history bias."""
        if not require_tools:
            return VerificationResult(
                ok=True,
                findings=["require_tools=False — L1 skipped"],
                level="L1",
                scores={},
            )
        Verifier.verify(
            findings=self._findings,
            records=self._records,
            require_tools=require_tools,
        )
        result = StructuralVerifier.verify(
            claim=claim,
            records=self._records,
            max_records=self._max_records,
            is_final_claim=True,
        )
        if not result.ok:
            raise VerifierError(result.to_error("L1"))
        return result

    # ── Serialization ───────────────────────────────────────────────────

    def to_serializable(self) -> dict:
        """Serialize all records to JSON-safe dicts (no FrozenSet)."""
        return {
            "records": [rec.to_dict() for rec in self._records.values()],
        }

    def restore(self, data: dict) -> None:
        """Replace all records from previously serialized data."""
        records_list = data.get("records", [])
        self._records = {}
        if not records_list:
            self._counter = 0
            return
        for item in records_list:
            rec = EvidenceRecord.from_dict(item)
            self._records[rec.evidence_id] = rec
        # Restore counter to avoid ID collision with existing records
        ids = [int(k.split("-")[1]) for k in self._records if k.startswith("E-")]
        self._counter = max(ids) if ids else 0

    @property
    def counter(self) -> int:
        """Expose counter for verification in tests."""
        return self._counter
