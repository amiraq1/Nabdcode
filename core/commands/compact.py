"""core/commands/compact.py — /compact command handler (V4.2).

Extracted from ui/repl_termux.py._handle_compact_command so that conversation
compaction logic (state.prune_history()) lives in core/, not the UI layer.
"""

from __future__ import annotations

from typing import Any, Optional


def estimate_message_tokens(messages: list[dict]) -> int:
    """Rough token estimate: ~4 chars per token."""
    total_chars = sum(len(m.get("content", "") or "") for m in messages)
    return max(1, total_chars // 4)


_COMPACT_MAX_TOKENS: int = 500


def handle_compact_command(agent: Any) -> dict:
    """Compact the agent's conversation history.

    Parameters
    ----------
    agent:
        The live agent whose RuntimeState will be compacted.

    Returns
    -------
    dict with keys:
        - success (bool)
        - old_tokens (int)
        - new_tokens (int)
        - saved (int)
        - error (str | None)
    """
    state = _resolve_state(agent)
    if not state:
        return {"success": False, "error": "No agent state available for compaction.",
                "old_tokens": 0, "new_tokens": 0, "saved": 0}

    old_messages = (
        state.get_messages() if hasattr(state, "get_messages")
        else getattr(state, "messages", [])
    )
    old_tokens = estimate_message_tokens(old_messages)

    try:
        saved_max = getattr(state, "max_context_tokens", 8192)
        if hasattr(state, "max_context_tokens"):
            state.max_context_tokens = _COMPACT_MAX_TOKENS
        if hasattr(state, "prune_history") and callable(state.prune_history):
            state.prune_history()
        elif hasattr(state, "clear_context") and callable(state.clear_context):
            state.clear_context()
        else:
            msgs = getattr(state, "messages", [])
            if msgs:
                sys_msgs = [m for m in msgs if m.get("role") == "system"]
                non_sys = [m for m in msgs if m.get("role") != "system"]
                state.messages = sys_msgs + non_sys[-4:]
        if hasattr(state, "max_context_tokens"):
            state.max_context_tokens = saved_max
    except Exception as exc:
        return {"success": False, "error": str(exc),
                "old_tokens": old_tokens, "new_tokens": old_tokens, "saved": 0}

    new_messages = (
        state.get_messages() if hasattr(state, "get_messages")
        else getattr(state, "messages", [])
    )
    new_tokens = estimate_message_tokens(new_messages)
    saved = old_tokens - new_tokens

    return {
        "success": True,
        "error": None,
        "old_tokens": old_tokens,
        "new_tokens": new_tokens,
        "saved": saved,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_state(agent: Any):
    """Best-effort resolve RuntimeState from agent (no UI dependency)."""
    if agent is None:
        return None
    try:
        from core.kernel.state import RuntimeState
        state = getattr(agent, "state", None) or getattr(agent, "runtime_state", None)
        if isinstance(state, RuntimeState):
            return state
    except Exception:
        pass
    return None
