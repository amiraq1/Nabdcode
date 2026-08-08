"""core/commands/plan_mode.py — plan mode injection handler (V4.5).

Extracted from ui/repl_termux.py so that:
- PLAN_MODE_INSTRUCTION constant lives in core/
- inject/restore logic for _msgs[0]["content"] lives in core/
- UI layer delegates to these functions
"""

from __future__ import annotations

from typing import Any, Optional

# The canonical plan mode instruction — single source of truth.
PLAN_MODE_INSTRUCTION: str = (
    "You are in PLAN MODE. Before executing any task:\n"
    "1. Use todo_write(action='plan', items=[...]) to outline your steps\n"
    "2. Get confirmation via final_answer() showing your plan\n"
    "3. Only then proceed with execution\n"
)


def inject_plan_mode(messages: list[dict]) -> Optional[str]:
    """Prepend PLAN_MODE_INSTRUCTION to the system message.

    Parameters
    ----------
    messages:
        The agent's message list (mutated in place).

    Returns
    -------
    str | None
        The original system message content (snapshot for later restore),
        or None if no system message was found.
    """
    if messages and len(messages) > 0 and messages[0].get("role") == "system":
        snapshot = messages[0]["content"]
        messages[0]["content"] = PLAN_MODE_INSTRUCTION + snapshot
        return snapshot
    return None


def restore_system_prompt(messages: list[dict], snapshot: str) -> None:
    """Restore the system message to its pre-plan-mode content.

    Parameters
    ----------
    messages:
        The agent's message list (mutated in place).
    snapshot:
        The original content returned by inject_plan_mode().
    """
    if messages and len(messages) > 0:
        messages[0]["content"] = snapshot


def get_agent_messages(agent: Any) -> Optional[list[dict]]:
    """Best-effort resolve the agent's messages list."""
    msgs = getattr(agent, "messages", None)
    if msgs is None:
        state = getattr(agent, "state", None)
        if state is not None:
            msgs = getattr(state, "messages", None)
    return msgs
