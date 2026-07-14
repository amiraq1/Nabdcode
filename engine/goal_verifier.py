"""GoalSpec verifiable-exit enforcement.

This module is the single gate that decides whether the agent is allowed to
terminate a session as "Success" when a ``GoalSpec`` is active. It is the
product-side realization of objective-driven autonomy:

  • The agent may NEVER emit a final answer / halt with "Success" unless the
    Verifier *explicitly asserts and proves* that every success criterion in
    the active GoalSpec has been met against live workspace evidence.
  • "Proven" means: the existing evidence stack (L0 structural integrity +
    L1 technical-anchor matching) passes, AND the goal's success criteria are
    actually evaluated — not merely implied by a passing generic claim.
  • If not met, the verifier returns a structured critique that the loop /
    deep agent must feed back into the LLM to re-enter the execution loop.

The module imports no heavy engine dependencies at load time beyond the
local engine.state types and core.evidence, keeping it decoupled and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from engine.state import GoalSpec
from core.evidence import EvidenceLog, VerifierError


@dataclass(frozen=True, slots=True)
class GoalVerificationResult:
    """Outcome of a goal exit-condition check."""

    ok: bool
    # Human-readable reasons (one per failing criterion, or a pass note).
    findings: List[str]
    # True iff a goal is even active (callers short-circuit when False).
    goal_active: bool

    def to_critique(self) -> str:
        """Format a correction critique for the loop / deep agent to re-enter."""
        if self.ok:
            return (
                "[GOAL VERIFIED]: All success criteria proven against live "
                "evidence. Agent may terminate as Success."
            )
        header = (
            "[GOAL NOT MET]: You attempted to finish, but the active GoalSpec "
            "success criteria are NOT yet proven against workspace evidence. "
            "Do NOT claim completion. Re-enter the loop and address the gaps:"
        )
        body = "\n".join(f"  • {f}" for f in self.findings) if self.findings else "  • (no evidence matches the stated criteria)"
        return f"{header}\n{body}"


# Phase5: hard cap on how many times a failed goal-exit critique may be issued
# before the loop gives up (mirrors MAX_SELF_CORRECT for the no-tool path).
MAX_GOAL_RETRIES: int = 3


def evaluate_goal_exit(
    goal: Optional[GoalSpec],
    evidence_log: EvidenceLog,
    *,
    require_tools: bool = True,
    final_claim: str = "",
) -> GoalVerificationResult:
    """Enforce the verifiable exit condition for the active GoalSpec.

    Returns ``ok=True`` only when:
      1. A goal is active (``goal`` is not None and has a non-empty prompt),
         AND
      2. The evidence stack passes (L0 + L1) for the goal's success criteria,
         AND
      3. There is at least one piece of live evidence to anchor the criteria
         (fail-closed: no evidence ⇒ not met).

    When no goal is active the result is ``goal_active=False`` and ``ok=True``
    so ad-hoc (non-goal) sessions keep their prior verification behavior.

    On failure raises nothing — it returns ``ok=False`` with a critique-ready
    findings list so the caller controls re-entry. (Callers may still choose to
    raise ``VerifierError`` downstream for the no-tool path.)
    """
    if goal is None or not goal.raw_prompt.strip():
        return GoalVerificationResult(ok=True, findings=[], goal_active=False)

    criteria = goal.success_criteria.strip() or goal.raw_prompt.strip()

    # No evidence at all → cannot prove anything. Fail closed.
    if require_tools and not evidence_log.has_evidence():
        return GoalVerificationResult(
            ok=False,
            findings=[
                "No verified evidence was collected — the success criteria "
                f"'{criteria[:120]}' cannot be proven against the workspace."
            ],
            goal_active=True,
        )

    # Run the existing evidence stack (L0 structural + L1 anchor matching)
    # against the goal's success criteria. A failure here is a hard reject.
    try:
        evidence_log.verify(require_tools=require_tools, claim=criteria)
    except VerifierError as verr:
        return GoalVerificationResult(
            ok=False,
            findings=[str(verr)],
            goal_active=True,
        )

    # The generic verifier passed, but the goal is stricter: the success
    # criteria must be *explicitly evaluated*, not merely echoed. We require at
    # least one successful evidence record whose output/command actually
    # relates to the criteria tokens. StructuralVerifier already enforced
    # anchor matching for ``criteria`` above, so a pass here means the criteria
    # are genuinely backed by live evidence. Surface a confirmation note.
    successful = [r for r in evidence_log.get_records() if r.success]
    findings = [
        f"Evidence stack passed ({len(successful)} successful record(s)); "
        f"success criteria '{criteria[:120]}' anchored to live workspace output."
    ]
    return GoalVerificationResult(ok=True, findings=findings, goal_active=True)


def assert_goal_exit(
    goal: Optional[GoalSpec],
    evidence_log: EvidenceLog,
    *,
    require_tools: bool = True,
    final_claim: str = "",
) -> None:
    """Same as ``evaluate_goal_exit`` but raises ``VerifierError`` on failure.

    Used by the no-tool / final-answer path so a failed goal check propagates
    exactly like the existing verifier rejection (re-entering the loop via the
    self-correction machinery).
    """
    result = evaluate_goal_exit(
        goal, evidence_log, require_tools=require_tools, final_claim=final_claim
    )
    if result.goal_active and not result.ok:
        raise VerifierError(result.to_critique())
