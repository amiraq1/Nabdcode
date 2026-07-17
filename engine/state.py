# engine/state.py — BRIDGE (Phase 6 DI)
#
# Backward-compatible re-export shim.  The canonical state module
# now lives at ``core/kernel/state.py``.  This file is preserved so
# every existing ``from engine.state import RuntimeState`` keeps
# working without editing 40+ files in one commit.
#
# NEW CODE should import directly from the canonical module:
#
#   from core.kernel.state import RuntimeState, GoalSpec, parse_goal_command
#

from core.kernel.state import (  # noqa: F401
    RuntimeState,
    GoalSpec,
    parse_goal_command,
    build_goal_block,
    ACTIVE_GOAL_TAG,
    MAX_CONTEXT_TOKENS,
    CHARS_PER_TOKEN,
    _estimate_tokens,
)

__all__ = [
    "RuntimeState",
    "GoalSpec",
    "parse_goal_command",
    "build_goal_block",
    "ACTIVE_GOAL_TAG",
    "MAX_CONTEXT_TOKENS",
    "CHARS_PER_TOKEN",
    "_estimate_tokens",
]
