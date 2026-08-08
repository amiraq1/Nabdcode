"""core/commands/goal.py — /goal command handler (V4.1).

Extracted from ui/repl_termux.py._handle_goal_command so that goal-setting
logic (state.active_goal = spec) lives in core/, not in the UI layer.

The UI layer calls handle_goal_command(text, agent) and receives a GoalSpec
(or None if text is not a /goal command); it then handles display/feedback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from core.kernel.state import GoalSpec, RuntimeState


def handle_goal_command(text: str, agent: Any = None) -> Optional["GoalSpec"]:
    """Parse and apply a /goal command to the agent's state.

    Parameters
    ----------
    text:
        The raw user input (e.g. ``/goal fix the bug || tests pass``).
    agent:
        The live agent whose RuntimeState will receive ``active_goal``.
        If None or the state cannot be resolved, the goal spec is still
        returned (the caller may apply it manually).

    Returns
    -------
    GoalSpec | None
        The parsed goal specification, or None if *text* is not a /goal
        command.
    """
    from core.kernel.state import parse_goal_command

    spec = parse_goal_command(text)
    if spec is None:
        return None

    state = _resolve_state(agent)
    if state is not None:
        state.active_goal = spec

    try:
        from core.ui_bridge import get_bridge
        bridge = get_bridge()
        bridge.emit("goal_set", goal_desc=spec.raw_prompt)
    except Exception:
        pass  # best-effort bridge notification

    return spec


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_state(agent: Any) -> Optional["RuntimeState"]:
    """Best-effort resolve RuntimeState from agent (no UI dependency)."""
    if agent is None:
        return None
    from core.kernel.state import RuntimeState
    state = getattr(agent, "state", None) or getattr(agent, "runtime_state", None)
    if isinstance(state, RuntimeState):
        return state
    return None
