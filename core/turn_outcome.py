"""
Phase 3 — TurnOutcome and LLMInvocationResult types.

TurnOutcome is the public terminal contract for a single agent turn.
LLMInvocationResult is the internal orchestration contract replacing
ambiguous ("", "") tuple returns.

Both are frozen dataclasses for immutability.  Imported by engine/loop.py,
engine/deep_agent.py, and main.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TurnStatus(str, Enum):
    """Terminal status for a single agent turn."""
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LLMInvocationStatus(str, Enum):
    """Internal status for a single LLM invocation.

    Replaces ambiguous ("", "") tuple returns so the orchestration
    layer can classify the result and decide retry vs. finalize.
    """
    SUCCESS = "SUCCESS"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    FATAL_ERROR = "FATAL_ERROR"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TurnOutcome:
    """Public terminal outcome of a single agent turn.

    Exactly one TurnOutcome is produced per started turn.  The
    exactly-once finalization authority (TurnFinalizer) enforces
    that the first valid commit wins and no duplicate is emitted.
    """

    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TurnStatus = TurnStatus.COMPLETED
    safe_message: str = ""
    """User-facing message describing the outcome."""

    final_answer: str = ""
    """The agent's final answer text (may be empty for FAILED/BLOCKED)."""

    failure_stage: str = ""
    """Stage at which the failure occurred (e.g. 'provider', 'tool', 'verifier')."""

    retryable: bool = False
    """True if the caller may retry the turn."""

    requires_review: bool = False
    """True if a human should review the outcome before proceeding."""

    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # finished_at has NO default — the TurnFinalizer always sets it.
    finished_at: str = ""

    def display_text(self) -> str:
        """Return the best user-facing text for this outcome.

        Priority: safe_message → final_answer → status name.
        """
        return self.safe_message or self.final_answer or self.status.value


@dataclass(frozen=True)
class LLMInvocationResult:
    """Internal structured result from a single LLM invocation.

    Replaces the legacy ``tuple[str, str]`` return from
    ``_invoke_llm_and_normalize`` so every path produces an explicit,
    typed result.  The orchestration layer inspects ``status`` to
    decide retry or terminal finalization.
    """

    status: LLMInvocationStatus = LLMInvocationStatus.SUCCESS
    content: str = ""
    """The model's response text (may be empty)."""

    error_type: str = ""
    """Type of the error (e.g. 'TimeoutError', 'ConnectionError')."""

    safe_message: str = ""
    """User-safe message (never includes sensitive provider details)."""

    retryable: bool = False
    """True if the orchestration layer may retry this invocation."""
