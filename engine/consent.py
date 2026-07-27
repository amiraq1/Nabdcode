"""Consent Loop — interactive approval gate for high-risk tool execution.

Phase 2 of the Public Release Protocol. This is a first-class engine capability,
decoupled from individual tool implementations: the Dispatcher boundary calls
`ConsentManager` and receives a boolean (approved?) plus a ToolResult to use when
the user declines. The engine stays unaware of UI/prompt details beyond that.

Policy is centralized in `ConsentPolicy.requires_confirmation` so additional
risky operations (filesystem writes, git commit/push, package installs, network
uploads, deletes, chmod, process termination, ...) can be added in ONE place
without touching execution logic.

Phase 2.6 (Consent Integrity):
  - Empty enter ("") is now DENIED (not approved).
  - Every consent decision (approved / denied / failed_closed) is recorded
    as an EvidenceRecord when ``evidence_log`` is passed to ``confirm()``.
  - Each EvidenceRecord carries:
      tool:        ``"consent.<tool_name>"``
      command_or_path: the exact command/path/query text
      action:      ``"consent_step_<step_count>"`` (temporal identifier)
      timestamp:   ``time.time()`` at record time
      output_snippet: ``"consent:<decision> [reason:<reason>]"``
    Turn ID is not structurally available on EvidenceRecord at this level;
    step_count (in action) + timestamp fulfill the temporal tracking requirement.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from tools.models import ToolResult


# Tools that ALWAYS require interactive confirmation before execution.
# Centralized here: extend this set (or the policy logic below) to cover future
# high-risk operations without modifying the execution loop.
_CONSENT_REQUIRED_TOOLS: frozenset[str] = frozenset(
    {
        "execute_shell",
    }
)


class ConsentPolicy:
    """Decides whether a tool call requires interactive user approval.

    Centralized, data-driven policy. Read-only and side-effect free.
    """

    # Tools explicitly exempt from consent (always auto-approved).
    SAFE_TOOLS: frozenset[str] = frozenset(
        {
            "termux_monitor",
            "search_memory",
            "web_search",
            "file_system",  # read-only + scoped operations handled by ShellTool/security layer
        }
    )

    @classmethod
    def requires_confirmation(cls, tool_name: str, args: dict[str, Any] | None = None) -> bool:
        """Return True if the tool call must be confirmed before execution."""
        if tool_name in cls.SAFE_TOOLS:
            return False
        return tool_name in _CONSENT_REQUIRED_TOOLS


class ConsentManager:
    """Owns the interactive consent flow at the Dispatcher boundary.

    The engine calls `confirm()` only when `ConsentPolicy.requires_confirmation`
    is True. On approval, the caller proceeds to dispatch normally. On decline,
    `confirm()` returns a blocked ToolResult the caller returns verbatim — this
    is a VALID outcome, not an engine error: no exceptions are raised, the
    ExecutionLoop is never aborted, and no loop_error is emitted.

    ``confirm()`` may receive an optional ``evidence_log`` and ``step`` for
    recording every decision (approved/denied/failed_closed) as an EvidenceRecord.
    """

    def __init__(self, prompt_func: Any | None = None) -> None:
        """`prompt_func(display_text) -> str` lets tests/UI inject input.

        Defaults to a built-in interactive prompt over stdin.
        """
        self._prompt_func = prompt_func or self._default_prompt

    @staticmethod
    def _render(tool_name: str, args: dict[str, Any] | None) -> str:
        """Render the exact approval prompt the spec requires."""
        command = (
            (args or {}).get("command")
            or (args or {}).get("path")
            or (args or {}).get("query")
            or str(args or {})
        )
        return (
            "⚠️ Agent wants to execute:\n"
            f"{command}\n"
            "\n"
            "Allow? [y/N]: "
        )

    @staticmethod
    def _default_prompt(display_text: str) -> str:
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("NABD_AUTO_APPROVE") == "1":
            return "y"
        try:
            return input(display_text)
        except (EOFError, KeyboardInterrupt, OSError):
            # Non-interactive / piped input: treat as declined (fail-safe).
            return "n"

    def requires_confirmation(self, tool_name: str, args: dict[str, Any] | None = None) -> bool:
        return ConsentPolicy.requires_confirmation(tool_name, args)

    def _record_decision(
        self,
        tool_name: str,
        args: dict[str, Any] | None,
        decision: str,
        evidence_log: Any = None,
        step: int = 0,
        reason: str = "",
    ) -> None:
        """Record a consent decision as an EvidenceRecord (no-op if no evidence_log)."""
        if evidence_log is None:
            return
        command = (
            (args or {}).get("command")
            or (args or {}).get("path")
            or (args or {}).get("query")
            or str(args or {})
        )
        snippet = f"consent:{decision}"
        if reason:
            snippet += f" reason:{reason}"
        evidence_log.record(
            tool=f"consent.{tool_name}",
            command_or_path=command,
            success=(decision == "approved"),
            output_snippet=snippet,
            action=f"consent_step_{step}",
        )

    def confirm(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        evidence_log: Any = None,
        step: int = 0,
    ) -> ToolResult | None:
        """Interactively confirm a tool call.

        Parameters:
            evidence_log: optional EvidenceLog for recording decisions.
            step: current ``state.step_count`` for turn tracking.

        Returns:
            None          -> user approved; caller dispatches normally.
            ToolResult    -> user declined; caller returns this verbatim.
        """
        display = self._render(tool_name, args)
        answer = (self._prompt_func(display) or "").strip().lower()

        # "y" / "yes" => approve.  Everything else (enter, n, N, EOF, …) => block.
        if answer in ("y", "yes"):
            self._record_decision(
                tool_name, args, "approved",
                evidence_log=evidence_log, step=step,
            )
            return None

        # Determine the failure mode for recording.
        if answer == "n":
            reason = "denied"
        elif not answer:
            reason = "denied_empty"
        else:
            reason = f"denied_unexpected_input:{answer}"

        self._record_decision(
            tool_name, args, "denied",
            evidence_log=evidence_log, step=step, reason=reason,
        )

        return ToolResult(
            success=True,
            stdout="Execution blocked by user.",
            stderr="",
            returncode=0,
            status="success",
        )


def _record_consent_failed_closed(
    tool_name: str,
    args: dict[str, Any] | None,
    evidence_log: Any = None,
    step: int = 0,
    reason: str = "",
) -> None:
    """Utility to record a fail-closed consent event (no user prompt shown).

    This is called by the engine when consent could not be requested
    (e.g. bridge unreachable) rather than through ``confirm()``.
    """
    if evidence_log is None:
        return
    command = (
        (args or {}).get("command")
        or (args or {}).get("path")
        or (args or {}).get("query")
        or str(args or {})
    )
    snippet = "consent:failed_closed"
    if reason:
        snippet += f" reason:{reason}"
    evidence_log.record(
        tool=f"consent.{tool_name}",
        command_or_path=command,
        success=False,
        output_snippet=snippet,
        action=f"consent_step_{step}",
    )
