from __future__ import annotations

from typing import Any, Callable
from core.constants import HARD_RULES
from core.monitoring import EventLogger
from llm_router import execute_agent_with_memory


class VerifierAgent:
    """Independent auditor verifying claims against evidence in fresh context."""

    def __init__(self, llm_fn: Callable[[list[dict[str, Any]]], str] | None = None):
        self.llm_fn = llm_fn or execute_agent_with_memory

    def verify_fresh(self, claim: str, evidence: str) -> bool:
        fresh = f"""[AUDIT]
{HARD_RULES}
Claim: {claim}
Evidence: {evidence[:3000]}
Verdict: PASS if evidence literally contains claim or supports it. Output PASS or FAIL."""
        result = self.llm_fn([{"role": "user", "content": fresh}])
        passed = "PASS" in result.upper()
        verdict = "PASS" if passed else "FAIL"
        EventLogger.log("verifier", "verify", verdict, claim=claim[:60])
        return passed
