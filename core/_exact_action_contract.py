"""
_exact_action_contract.py — Single source of truth for Exact-Action Mode.

Exact-action mode restricts the agent to executing exactly one shell command
and returning its output — no exploration, no file reads, no TODOs.

Contract:
----------
1. EXACT_ACTION_ALLOWED_TOOLS contains only "execute_shell".
2. "final_answer" is deliberately excluded from the LLM tool schema.
   It is injected only as a system-level control message by the Convergence
   Gate (``_emit_final``) after the single shell command completes.
3. Runtime enforcement (``_guard_exact_action`` in engine/loop.py) blocks
   any tool call other than ``execute_shell`` before it reaches the
   dispatcher.
4. The single-tool schema means the model can ONLY call ``execute_shell``.
   After execution, ``_exact_action_tool_count >= 1`` triggers
   ``_force_final = True``, which terminates via ``_maybe_force_partial_answer``
   → ``_emit_final`` without an additional LLM call.
"""

from __future__ import annotations

from typing import Final, FrozenSet


# ── Canonical set of allowed tools in exact-action mode ─────────────────
# "final_answer" is NOT listed here; it is handled as a system-level
# control message (see module docstring).
EXACT_ACTION_ALLOWED_TOOLS: Final[FrozenSet[str]] = frozenset({"execute_shell"})

# ── Flag for test/assertion use ────────────────────────────────────────
EXACT_ACTION_FINAL_ANSWER_IS_CONTROL_MESSAGE: Final[bool] = True

# ── Prompt patterns that trigger exact-action mode ─────────────────────
EXACT_ACTION_PATTERNS: Final[list[str]] = [
    "exactly one shell command",
    "exactly one command",
    "single shell command",
    "one shell command only",
    "run exactly one",
]
