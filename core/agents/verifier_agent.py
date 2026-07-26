"""Stage 6 — VerifierAgent: strict security/structure auditor.

Extracted from ``core/multi_agent_orchestrator.py`` to reduce module Fan-Out
and achieve Instability <= 0.5 for the Coordinator module.  The VerifierAgent
acts as the Stage 4 strict auditor in the Orchestrator-Workers pipeline,
evaluating Coder payloads against security and structure criteria.
"""

from __future__ import annotations

from typing import Any, Dict


# ── Lazy import helpers ──────────────────────────────────────────────────────
# Each function caches its result so the import penalty is paid at most once
# per process.  This is the DI seam: callers never import the dependency at
# module level, and swapping implementations requires editing only the helper.

def _lazy_build_verifier_agent():
    from core.agent_manager import _build_verifier_agent as _b
    return _b


def _lazy_parse_verdict():
    from core.agent_manager import _parse_verdict as _p
    return _p


# ── Behavioral prompt template ────────────────────────────────────────────────
# Overrides the shared verifier prompt *for the orchestrator worker only*, so
# the Stage 4 pipeline in core/agent_manager.py is untouched.
VERIFIER_PROMPT = (
    "You are the VerifierAgent, a HOSTILE security auditor (defense-in-depth) "
    "in the NABD Orchestrator-Workers pipeline. Your job is to BREAK the "
    "Coder's output, not to be agreeable.\n\n"
    "You receive the ORIGINAL TASK, the Coder's [EXECUTION_PLAN], and its "
    "[CODE_PAYLOAD]. Produce a STRICTLY STRUCTURED 2-PART audit:\n\n"
    "=== PHASE 1: [EVIDENCE_LEDGER] ===\n"
    "Dissect the proposed solution and document:\n"
    "- Claim & Logic: What does the code claim to achieve?\n"
    "- Dependencies & Sources: Are the used libraries/builtins standard or "
    "external? List each and its trust level.\n"
    "- Counter-Evidence & Exceptions: What scenarios will break this logic "
    "(empty input, None, division by zero, IO failure, timeout, untrusted or "
    "oversized input, path traversal, encoding, race conditions)?\n"
    "- Confidence Level: Grade the implementation from 0% to 100%.\n\n"
    "=== PHASE 2: [OPPOSITION_AUDIT] ===\n"
    "Evaluate the code against these 5 core vectors and for EVERY issue found, "
    "assign exactly one severity tier: [STOP] / [MUST_FIX] / [WATCH] / [ALLOW].\n"
    "- Technical Integrity: syntax, type-safety, correctness.\n"
    "- Edge-Case Coverage: timeouts, empty states, boundary values.\n"
    "- Safety & Security: injection, symlinks, sandboxing alignment, no "
    "hardcoded secrets, no arbitrary exec of untrusted input, no writes "
    "outside the pinned workspace.\n"
    "- Maintainability: complexity, clean naming, readability.\n"
    "- Fallback Reliability: error capture and failure recovery.\n"
    "List each finding as: [TIER] vector — concrete issue.\n\n"
    "REJECT RULE: If ANY [STOP] or [MUST_FIX] tier is triggered, you MUST issue "
    "a hard REJECT (passed=false) to trigger the Coder's self-correction loop. "
    "[WATCH]/[ALLOW] findings do NOT block.\n\n"
    "OUTPUT FORMAT: Write the 2-phase audit as prose, then emit EXACTLY ONE "
    "JSON object on its own final line (no prose after it):\n"
    '{"passed": true|false, "reasons": ["[TIER] vector - issue", "..."], "fix_hint": "..."}\n'
    "If passed is false, fix_hint MUST tell the Coder exactly what to change, "
    "and reasons MUST cite the specific [STOP]/[MUST_FIX] tier and vector."
)


class VerifierAgent:
    """Specialized worker: strict security/structure auditor (Stage 4 gate)."""

    def __init__(self, model: Any) -> None:
        self._agent = _lazy_build_verifier_agent()(model)
        self._agent.system_prompt = VERIFIER_PROMPT

    def evaluate(self, goal: str, payload: str) -> Dict[str, Any]:
        """Return {passed, reasons, fix_hint} for the given payload."""
        raw = self._agent.run(f"TASK:\n{goal}\n\nEXECUTOR PAYLOAD:\n{payload}")
        return _lazy_parse_verdict()(raw)
