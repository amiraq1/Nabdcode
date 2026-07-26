"""
Phase 3 — Exactly-Once Turn Finalization Authority.

Guarantees that every started turn produces exactly one terminal
TurnOutcome.  The first valid finalization commit wins; subsequent
attempts are recorded as duplicate diagnostics but do NOT overwrite
the original outcome or emit a second terminal event.

Thread-safe via threading.Lock.  No global state — one finalizer
per turn.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import dataclasses
from core.turn_outcome import TurnOutcome, TurnStatus


@dataclass
class _DuplicateDiagnostic:
    """Record of a duplicate finalization attempt (not exposed as outcome)."""
    attempted_status: str
    attempted_message: str
    timestamp: str


class TurnFinalizer:
    """Exactly-once turn finalization authority.

    Usage::

        finalizer = TurnFinalizer()
        ok = finalizer.finalize(TurnOutcome(status=TurnStatus.COMPLETED, ...))
        if not ok:
            # Diagnostic recorded; original outcome preserved.

    Thread-safe.  No global state.  Create one per turn.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._outcome: Optional[TurnOutcome] = None
        self._is_finalized: bool = False
        self._duplicate_diagnostics: list[_DuplicateDiagnostic] = []
        # Event for the prompt gate to wait on (set when outcome is finalized).
        self._outcome_event = threading.Event()

    @property
    def outcome(self) -> Optional[TurnOutcome]:
        """Return the terminal outcome, or None if not yet finalized."""
        with self._lock:
            return self._outcome

    @property
    def is_finalized(self) -> bool:
        """True when the first terminal outcome has been committed."""
        with self._lock:
            return self._is_finalized

    @property
    def duplicate_diagnostics(self) -> list[_DuplicateDiagnostic]:
        """Read-only copy of duplicate finalization diagnostics."""
        with self._lock:
            return list(self._duplicate_diagnostics)

    def finalize(self, outcome: TurnOutcome) -> bool:
        """Commit *outcome* as the terminal result.

        If this is the first finalization, it is accepted and stored.
        If a prior outcome already exists, the attempt is recorded as
        a duplicate diagnostic and rejected.

        Returns True on first successful commit, False on duplicate.
        NEVER emits or publishes events — the caller does that.
        """
        if outcome is None:
            raise TypeError("TurnFinalizer.finalize() requires a TurnOutcome")

        with self._lock:
            if self._is_finalized:
                self._duplicate_diagnostics.append(_DuplicateDiagnostic(
                    attempted_status=outcome.status.value,
                    attempted_message=outcome.safe_message[:200],
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
                return False

            # Ensure finished_at is set
            if not outcome.finished_at:
                outcome = dataclasses.replace(
                    outcome,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )

            self._outcome = outcome
            self._is_finalized = True
            self._outcome_event.set()
            return True

    def wait_for_outcome(self, timeout: Optional[float] = None) -> Optional[TurnOutcome]:
        """Block until a terminal outcome is committed, then return it.

        Returns None on timeout.  Safe to call from the prompt gate.
        """
        self._outcome_event.wait(timeout=timeout)
        return self.outcome

    def reset(self) -> None:
        """Reset the finalizer for a new turn.

        Clears outcome, diagnostics, and event.  Call ONCE between turns.
        """
        with self._lock:
            self._outcome_event.clear()  # clear BEFORE resetting state
            self._outcome = None
            self._is_finalized = False
            self._duplicate_diagnostics.clear()
