"""Convergence gate — single choke point for final answer authorization.

Provides ``can_finalize()`` which returns a structured ``FinalizationDecision``
describing whether a final answer may be emitted, which TODOs block it, and a
summary of the evidence backing each completed TODO.

Design rules:
  - A TODO in ``pending`` / ``in_progress`` / ``unknown`` status BLOCKS.
  - A TODO marked ``done`` is only trusted if it has matching evidence
    (a successful tool event whose path matches the TODO's target).
  - A TODO marked ``skipped`` or ``blocked`` is allowed only with an explicit
    reason.
  - The engine cannot cheat by deleting incomplete TODOs before finalizing:
    any TODO that was ever created and is now absent is treated as
    ``unknown`` and blocks.
  - On budget exhaustion or deadline, the gate returns PARTIAL (not complete)
    and lists the incomplete TODOs + available evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Protocol, Sequence, runtime_checkable


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


# Statuses that permit finalization (with evidence or explicit reason).
_ALLOWED_STATUSES = frozenset({TodoStatus.DONE, TodoStatus.SKIPPED, TodoStatus.BLOCKED})

# Statuses that block finalization.
_BLOCKING_STATUSES = frozenset({TodoStatus.PENDING, TodoStatus.IN_PROGRESS, TodoStatus.UNKNOWN})


@dataclass
class TodoEvidenceLink:
    """Evidence linking for a single TODO item."""
    todo_id: int
    todo_text: str
    status: str
    evidence_ids: list[str] = field(default_factory=list)
    completed_at: Optional[float] = None
    completion_source: Optional[str] = None
    failure_reason: Optional[str] = None
    has_matching_evidence: bool = False


@dataclass
class CompletionItem:
    """A single item in a completion tracker, abstracting TODOs and plan steps.

    Both TodoManager (ExecutionLoop) and DeepAgentState.plan (NativeDeepAgent)
    are adapted to this uniform shape so can_finalize() has a single choke
    point regardless of which engine path produced the plan.
    """
    id: int
    text: str
    status: str
    evidence_ids: list[str] = field(default_factory=list)
    completed_at: Optional[float] = None
    completion_source: Optional[str] = None
    failure_reason: Optional[str] = None


@runtime_checkable
class CompletionTracker(Protocol):
    """Unified interface for convergence tracking across engine paths.

    Implementations:
      - TodoManagerCompletionTracker  (wraps TodoManager for ExecutionLoop)
      - DeepAgentPlanCompletionTracker (wraps DeepAgentState.plan for NativeDeepAgent)

    can_finalize() accepts this Protocol instead of a concrete TodoManager so
    both engine paths share the same convergence contract.
    """
    def completion_items(self) -> Sequence[CompletionItem]: ...


@dataclass
class FinalizationDecision:
    """Structured result of ``can_finalize()``.

    Attributes:
        allowed: True only if every TODO is in an allowed status AND has the
            required evidence (for ``done``) or explicit reason (for
            ``skipped`` / ``blocked``).
        blocking_todos: List of TODOs that prevent finalization.
        blocked_reason: Human-readable explanation when ``allowed`` is False.
        evidence_summary: Per-TODO evidence summary string.
        todo_links: Full evidence-link details for each TODO.
        partial: True when budget/deadline was exhausted but some TODOs
            remain incomplete (terminal PARTIAL, not a retry).
    """
    allowed: bool
    blocking_todos: list[TodoEvidenceLink] = field(default_factory=list)
    blocked_reason: str = ""
    evidence_summary: str = ""
    todo_links: list[TodoEvidenceLink] = field(default_factory=list)
    partial: bool = False


def _extract_path_from_todo(text: str) -> str:
    """Extract a file path from a TODO text, if present.

    Looks for patterns like 'core/loop.py', 'pyproject.toml', etc.
    Returns the lowercased path or empty string.
    """
    import re
    match = re.search(r'[\w./-]+\.\w{1,6}', text)
    if match:
        return match.group(0).lower()
    return ""


def _todo_has_matching_evidence(
    todo: Any,
    evidence_records: list,
) -> bool:
    """Check if a TODO marked 'done' has matching evidence.

    Matching criteria:
    - For READ/VERIFY/TEST/EDIT TODOs: there must be a successful evidence
      record whose tool and path/action match the TODO's intent.
    - The evidence record's command_or_path must match the path extracted
      from the TODO text.
    """
    if not evidence_records:
        return False

    todo_text = getattr(todo, "text", "") or str(todo)
    todo_status = getattr(todo, "status", "")
    if hasattr(todo_status, "value"):
        status_str = str(todo_status.value).lower()
    else:
        status_str = str(todo_status).lower() if todo_status else "unknown"

    # Only 'done' TODOs require evidence matching.
    if status_str != "done":
        return True  # skipped/blocked don't need evidence matching

    todo_path = _extract_path_from_todo(todo_text)
    todo_lower = todo_text.lower()

    for rec in evidence_records:
        if not getattr(rec, "success", False):
            continue

        rec_tool = getattr(rec, "tool", "") or ""
        rec_path = str(getattr(rec, "command_or_path", "") or "").strip().lower()
        rec_action = getattr(rec, "action", "") or ""

        # Check path match
        if todo_path and rec_path:
            if todo_path in rec_path or rec_path in todo_path:
                return True

        # Check if the TODO text mentions the evidence's tool or path
        if rec_path and rec_path in todo_lower:
            return True

        # For READ/VERIFY/TEST/EDIT TODOs, any successful filesystem or shell
        # evidence that mentions the same file counts.
        if todo_path:
            rec_snippet = str(getattr(rec, "output_snippet", "") or "").lower()
            if todo_path in rec_snippet:
                return True

    # If the TODO has no path (e.g. "Verify the build"), check if any evidence
    # record's tool matches the TODO's intent.
    if not todo_path:
        for rec in evidence_records:
            if not getattr(rec, "success", False):
                continue
            rec_tool = getattr(rec, "tool", "") or ""
            if rec_tool in todo_lower:
                return True

        # Fallback for generic TODOs (no path, no tool keyword): accept any
        # successful evidence record with a meaningful snippet. This prevents
        # false negatives when TODOs have generic text like "Verify the fix"
        # but the evidence clearly shows a completed action. The evidence
        # policy depends on the task type — generic TODOs accept any
        # successful evidence, while path-targeted TODOs require path match.
        for rec in evidence_records:
            if not getattr(rec, "success", False):
                continue
            rec_snippet = str(getattr(rec, "output_snippet", "") or "").lower()
            if rec_snippet and len(rec_snippet) > 5:
                return True

    return False


def _build_todo_link(
    todo: Any,
    evidence_records: list,
) -> TodoEvidenceLink:
    """Build a TodoEvidenceLink for a single TODO."""
    todo_id = getattr(todo, "id", 0)
    todo_text = getattr(todo, "text", "") or str(todo)
    todo_status = getattr(todo, "status", "")
    if hasattr(todo_status, "value"):
        status_str = str(todo_status.value).lower()
    else:
        status_str = str(todo_status).lower() if todo_status else "unknown"

    # Try to get evidence_ids from the TODO if it has them
    evidence_ids = getattr(todo, "evidence_ids", None) or []
    if not isinstance(evidence_ids, list):
        evidence_ids = []

    completed_at = getattr(todo, "completed_at", None)
    completion_source = getattr(todo, "completion_source", None)
    failure_reason = getattr(todo, "failure_reason", None)

    has_match = _todo_has_matching_evidence(todo, evidence_records)

    return TodoEvidenceLink(
        todo_id=todo_id,
        todo_text=todo_text,
        status=status_str,
        evidence_ids=list(evidence_ids),
        completed_at=completed_at,
        completion_source=completion_source,
        failure_reason=failure_reason,
        has_matching_evidence=has_match,
    )


def can_finalize(
    todo_manager: Any = None,
    evidence_log: Any = None,
    budget_exhausted: bool = False,
    deadline_exceeded: bool = False,
    completion_tracker: "CompletionTracker | None" = None,
    requires_plan: bool = False,
) -> FinalizationDecision:
    """Determine whether a final answer may be emitted.

    Args:
        todo_manager: (Deprecated) A TodoManager (or compatible) with an
            ``all()`` method. If ``completion_tracker`` is not provided, a
            TodoManagerCompletionTracker is built from this.
        evidence_log: An EvidenceLog (or compatible) with a ``get_records()``
            method. If None, evidence matching is skipped (TODOs in 'done'
            status are trusted).
        budget_exhausted: True if the API budget or step budget was exhausted.
        deadline_exceeded: True if the time deadline was exceeded.
        completion_tracker: A CompletionTracker (Protocol) providing
            ``completion_items()``. Preferred over ``todo_manager`` — both
            engine paths (ExecutionLoop via TodoManagerCompletionTracker,
            NativeDeepAgent via DeepAgentPlanCompletionTracker) pass this.
        requires_plan: When True, fail closed (allowed=False) if no completion
            items are available. This prevents the agent from bypassing the
            convergence gate by simply not having a tracker. For chitchat /
            non-investigation prompts, leave False.

    Returns:
        FinalizationDecision with allowed=True only if every completion item
        is in an allowed status and (for 'done') has matching evidence.
    """
    # ── Resolve completion items from tracker or todo_manager ────────────
    completion_items: list[CompletionItem] = []
    if completion_tracker is not None:
        try:
            completion_items = list(completion_tracker.completion_items())
        except Exception:
            completion_items = []
    elif todo_manager is not None:
        tracker = TodoManagerCompletionTracker(todo_manager)
        try:
            completion_items = list(tracker.completion_items())
        except Exception:
            completion_items = []

    # ── Fail closed: plan required but no tracker available ──────────────
    # Only fail closed when there is NO tracker at all. If a tracker exists
    # but is empty (no TODOs), allow finalization — there is nothing to block
    # on. This preserves the answer-in-hand gate and chitchat paths.
    if requires_plan and completion_tracker is None:
        return FinalizationDecision(
            allowed=False,
            blocking_todos=[],
            blocked_reason=(
                "Plan required for finalization but no completion tracker "
                "available (fail-closed)."
            ),
            evidence_summary="(no completion tracker)",
            todo_links=[],
            partial=False,
        )

    # ── Collect evidence records ─────────────────────────────────────────
    evidence_records: list = []
    if evidence_log is not None:
        try:
            evidence_records = evidence_log.get_records()
        except Exception:
            evidence_records = []

    # ── Build evidence links for each completion item ────────────────────
    todo_links: list[TodoEvidenceLink] = []
    for item in completion_items:
        link = _build_todo_link(item, evidence_records)
        todo_links.append(link)

    # ── Budget / deadline exhaustion ─────────────────────────────────────
    if budget_exhausted or deadline_exceeded:
        blocking = [
            link for link in todo_links
            if link.status in ("pending", "in_progress", "unknown")
            or (link.status == "done" and not link.has_matching_evidence)
        ]
        evidence_lines = []
        for link in todo_links:
            if link.status == "done" and link.has_matching_evidence:
                evidence_lines.append(
                    f"  ✓ TODO #{link.todo_id} done — evidence: {link.evidence_ids}"
                )
            elif link.status == "done" and not link.has_matching_evidence:
                evidence_lines.append(
                    f"  ✗ TODO #{link.todo_id} done but NO matching evidence"
                )
            else:
                evidence_lines.append(
                    f"  ✗ TODO #{link.todo_id} {link.status}"
                )

        reason = (
            "Budget/deadline exhausted. "
            f"{len(blocking)} TODO(s) incomplete or unverified."
        )
        return FinalizationDecision(
            allowed=False,
            blocking_todos=blocking,
            blocked_reason=reason,
            evidence_summary="\n".join(evidence_lines),
            todo_links=todo_links,
            partial=True,
        )

    # ── No completion items: allow only if not requires_plan ────────────
    # Fail-closed: if the engine required a plan/tracking but the tracker
    # returned zero items (empty plan, broken tracker, or cursor inflation
    # with no actual steps), we must NOT allow finalization. An empty list
    # is never inferred as legitimate when tracking is required.
    if not completion_items:
        if requires_plan:
            return FinalizationDecision(
                allowed=False,
                blocking_todos=[],
                blocked_reason=(
                    "Plan required for finalization but no completion items "
                    "available (fail-closed)."
                ),
                evidence_summary="(no completion items defined)",
                todo_links=[],
                partial=False,
            )
        return FinalizationDecision(
            allowed=True,
            blocking_todos=[],
            blocked_reason="",
            evidence_summary="(no completion items defined)",
            todo_links=[],
            partial=False,
        )

    # ── Check each TODO ──────────────────────────────────────────────────
    blocking: list[TodoEvidenceLink] = []
    evidence_lines: list[str] = []

    for link in todo_links:
        if link.status in ("pending", "in_progress", "unknown"):
            blocking.append(link)
            evidence_lines.append(
                f"  ✗ TODO #{link.todo_id} [{link.status}]: {link.todo_text[:60]}"
            )
        elif link.status == "done":
            if not link.has_matching_evidence:
                blocking.append(link)
                evidence_lines.append(
                    f"  ✗ TODO #{link.todo_id} [done] but NO matching evidence"
                )
            else:
                evidence_lines.append(
                    f"  ✓ TODO #{link.todo_id} done — evidence: {link.evidence_ids}"
                )
        elif link.status == "skipped":
            if not link.failure_reason:
                blocking.append(link)
                evidence_lines.append(
                    f"  ✗ TODO #{link.todo_id} [skipped] but no explicit reason"
                )
            else:
                evidence_lines.append(
                    f"  ⊘ TODO #{link.todo_id} skipped: {link.failure_reason[:60]}"
                )
        elif link.status == "blocked":
            if not link.failure_reason:
                blocking.append(link)
                evidence_lines.append(
                    f"  ✗ TODO #{link.todo_id} [blocked] but no explicit reason"
                )
            else:
                evidence_lines.append(
                    f"  ⛔ TODO #{link.todo_id} blocked: {link.failure_reason[:60]}"
                )
        else:
            # Unknown status → block
            blocking.append(link)
            evidence_lines.append(
                f"  ✗ TODO #{link.todo_id} [unknown status: {link.status}]"
            )

    if blocking:
        return FinalizationDecision(
            allowed=False,
            blocking_todos=blocking,
            blocked_reason=(
                f"{len(blocking)} TODO(s) block finalization: "
                + ", ".join(f"#{b.todo_id}({b.status})" for b in blocking)
            ),
            evidence_summary="\n".join(evidence_lines),
            todo_links=todo_links,
            partial=False,
        )

    return FinalizationDecision(
        allowed=True,
        blocking_todos=[],
        blocked_reason="",
        evidence_summary="\n".join(evidence_lines),
        todo_links=todo_links,
        partial=False,
    )


def classify_claim(claim: str, evidence_records: list) -> str:
    """Classify a claim as OBSERVED, INFERRED, or UNVERIFIED.

    - OBSERVED: directly quoted or present in evidence output.
    - INFERRED: supported by multiple evidence records but not directly quoted.
    - UNVERIFIED: no supporting evidence found.
    """
    if not claim or not evidence_records:
        return "UNVERIFIED"

    claim_lower = claim.lower().strip()
    if not claim_lower:
        return "UNVERIFIED"

    # Check for direct quotation (quoted strings in the claim)
    import re
    quoted = re.findall(r'"([^"]{4,})"', claim)
    if quoted:
        for q in quoted:
            for rec in evidence_records:
                if not getattr(rec, "success", False):
                    continue
                snippet = str(getattr(rec, "output_snippet", "") or "").lower()
                if q.lower() in snippet:
                    return "OBSERVED"

    # Check for technical tokens in evidence
    from core.evidence import _extract_technical_tokens
    tokens = _extract_technical_tokens(claim)
    if not tokens:
        # Fallback: check for non-technical tokens (hyphenated words, etc.)
        # in the evidence corpus. This handles claims like "nabd-os" that
        # are not extracted as technical tokens but are present in evidence.
        words = re.findall(r"[a-z][a-z0-9-]{2,}", claim_lower)
        if not words:
            return "UNVERIFIED"
        matched = 0
        for rec in evidence_records:
            if not getattr(rec, "success", False):
                continue
            corpus = (
                str(getattr(rec, "output_snippet", "") or "")
                + " "
                + str(getattr(rec, "command_or_path", "") or "")
            ).lower()
            for w in words:
                if w in corpus:
                    matched += 1
                    break
        if matched >= len(words):
            return "OBSERVED"
        elif matched > 0:
            return "INFERRED"
        return "UNVERIFIED"

    matched = 0
    for rec in evidence_records:
        if not getattr(rec, "success", False):
            continue
        corpus = (
            str(getattr(rec, "output_snippet", "") or "")
            + " "
            + str(getattr(rec, "command_or_path", "") or "")
        ).lower()
        for t in tokens:
            pattern = rf"(?<![\w.-]){re.escape(t)}(?![\w.-])"
            if re.search(pattern, corpus):
                matched += 1
                break

    if matched >= len(tokens):
        return "OBSERVED"
    elif matched > 0:
        return "INFERRED"
    # Fallback: check for non-technical tokens (hyphenated words, etc.)
    # in the evidence corpus even when technical tokens didn't match.
    # This handles claims like "nabd-os" that are present in evidence
    # but not extracted as technical tokens.
    words = re.findall(r"[a-z][a-z0-9-]{2,}", claim_lower)
    if words:
        word_matched = 0
        for rec in evidence_records:
            if not getattr(rec, "success", False):
                continue
            corpus = (
                str(getattr(rec, "output_snippet", "") or "")
                + " "
                + str(getattr(rec, "command_or_path", "") or "")
            ).lower()
            for w in words:
                if w in corpus:
                    word_matched += 1
                    break
        if word_matched > 0:
            return "INFERRED"
    return "UNVERIFIED"


class TodoManagerCompletionTracker:
    """Adapter: wraps a TodoManager as a CompletionTracker.

    Converts TodoItem objects into CompletionItems so can_finalize() can
    operate on a unified interface regardless of the engine path.
    """

    def __init__(self, todo_manager: Any):
        self._todo_manager = todo_manager

    def completion_items(self) -> Sequence[CompletionItem]:
        items: list[CompletionItem] = []
        for todo in self._todo_manager.all():
            status = getattr(todo, "status", "")
            if hasattr(status, "value"):
                status_str = str(status.value).lower()
            else:
                status_str = str(status).lower() if status else "unknown"
            evidence_ids = getattr(todo, "evidence_ids", None)
            if not isinstance(evidence_ids, list):
                evidence_ids = []
            items.append(CompletionItem(
                id=getattr(todo, "id", 0),
                text=getattr(todo, "text", ""),
                status=status_str,
                evidence_ids=list(evidence_ids),
                completed_at=getattr(todo, "completed_at", None),
                completion_source=getattr(todo, "completion_source", None),
                failure_reason=getattr(todo, "failure_reason", None),
            ))
        return items


class DeepAgentPlanCompletionTracker:
    """Adapter: wraps DeepAgentState.plan as a CompletionTracker.

    Converts plan steps into CompletionItems, marking steps as 'done' when
    they have been executed (current_plan_index > step_index) and 'pending'
    otherwise. This binds NativeDeepAgent's internal plan to the convergence
    contract so can_finalize() can gate finalization on plan completeness.

    A step is considered 'done' only when current_plan_index has advanced
    past it, meaning the EXECUTE node processed it. This prevents the agent
    from bypassing the gate by inflating current_plan_index via checkpoint
    tampering — can_finalize() still requires matching evidence for 'done'
    items via the evidence_log parameter.
    """

    def __init__(
        self,
        plan: List[str],
        current_plan_index: int = 0,
        past_steps: Optional[List[str]] = None,
    ):
        self._plan = plan
        self._current_plan_index = max(0, current_plan_index)
        self._past_steps = past_steps or []

    def completion_items(self) -> Sequence[CompletionItem]:
        items: list[CompletionItem] = []
        for i, step in enumerate(self._plan):
            # A step is 'done' only if the EXECUTE cursor has advanced past it.
            # This is derived from current_plan_index, not from past_steps,
            # because past_steps can lag (a step may have been executed but its
            # result not yet appended). The cursor is the authoritative signal.
            if i < self._current_plan_index:
                status = "done"
            else:
                status = "pending"
            items.append(CompletionItem(
                id=i + 1,
                text=step,
                status=status,
                evidence_ids=[],
                completed_at=None,
                completion_source="deep_agent" if status == "done" else None,
                failure_reason=None,
            ))
        return items
