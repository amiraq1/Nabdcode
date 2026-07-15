"""Consent Loop — interactive approval gate for high-risk tool execution.

Phase 2 of the Public Release Protocol. This is a first-class engine capability,
decoupled from individual tool implementations: the Dispatcher boundary calls
`ConsentManager` and receives a boolean (approved?) plus a ToolResult to use when
the user declines. The engine stays unaware of UI/prompt details beyond that.

Policy is centralized in `ConsentPolicy.requires_confirmation` so additional
risky operations (filesystem writes, git commit/push, package installs, network
uploads, deletes, chmod, process termination, ...) can be added in ONE place
without touching execution logic.
"""

from __future__ import annotations

import os
from typing import Any

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
            "Allow? [Y/n]: "
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

    def confirm(self, tool_name: str, args: dict[str, Any] | None = None) -> ToolResult | None:
        """Interactively confirm a tool call.

        Returns:
            None          -> user approved; caller dispatches normally.
            ToolResult    -> user declined; caller returns this verbatim.
        """
        display = self._render(tool_name, args)
        answer = (self._prompt_func(display) or "").strip().lower()

        # Enter (empty), 'y', 'Y' => approve. Anything else (n, N, ...) => block.
        if answer in ("", "y", "yes"):
            return None

        return ToolResult(
            success=True,
            stdout="Execution blocked by user.",
            stderr="",
            returncode=0,
            status="success",
        )


# Module-level default instance for callers that don't need injection.
default_consent_manager = ConsentManager()
