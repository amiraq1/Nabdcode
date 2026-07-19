from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from core.parser import ToolCall
from core.prompts import BROWSER_FEWSHOT_EXAMPLES, CRITICAL_RULES_FOR_TOOL_CALLING


# ── Shared loop constants (consumed by context + dispatch mixins) ────────────
TOOL_WINDOW: Final[int] = 2
CHAT_WINDOW: Final[int] = 12
MAX_CRITICAL_FULL: Final[int] = 3

TOOL_FEWSHOT_FALLBACK: Final[str] = (
    f"{CRITICAL_RULES_FOR_TOOL_CALLING}\n\n"
    "## Tool Call Format (few-shot)\n"
    "You MUST call a tool by outputting ONLY one JSON object. No prose.\n\n"
    "Example 1 — search the local codebase knowledge base (RAG) for code context:\n"
    '{"tool": "search_knowledge_base", "args": {"action": "search", "query": "EventBus fault isolation try except", "k": 3}}\n\n'
    "Example 2 — run a shell command:\n"
    '{"tool": "execute_shell", "args": {"command": "ls -la"}}\n\n'
    "Example 3 — finish a conversational reply:\n"
    '{"tool": "final_answer", "args": {"answer": "Here is your answer."}}\n\n'
    f"{BROWSER_FEWSHOT_EXAMPLES}\n\n"
    "Output ONLY one JSON object. No prose."
)


class _LoopSignal(Enum):
    """Control signal returned by extracted helpers to drive the orchestrator.

    Helpers never call ``continue``/``return`` on the loop directly; they emit
    the appropriate ``bus`` events and signal the orchestrator what to do next,
    preserving the exact pre-refactor control flow.
    """

    CONTINUE = "continue"   # skip the rest of this iteration (continue)
    TERMINATE = "terminate"  # leave the loop entirely (return)
    PROCEED = "proceed"     # keep going through the iteration body
    FINAL_ANSWER = "final_answer"  # smolagents termination convention, handled as a clean stop


@dataclass
class _ToolInteraction:
    """One completed tool turn, captured for Phase4 contextual compaction.

    Strict schema (no free text beyond ``summary``)::
      step:      int   — monotonic loop step counter
      tool:      str   — resolved tool name (execute_shell / file_system / …)
      ok:        bool  — exit success
      exit_code: int   — process return code (0 on success)
      path_hint: str   — command/path/query the tool was invoked with
      summary:   str   — 1-line human-readable outcome (kept in summaries)
      output:    str   — raw output, retained ONLY inside TOOL_WINDOW
      evidence_id: str — E-id for critical-evidence freezing
      critical:  bool  — surfaced via Auto-Critical Policy

    The full ``output`` (possibly huge) is retained only while this interaction
    sits inside the sliding window. Once outside the window it is discarded and
    replaced by a structural ``<past_steps_summary>`` record. Critical turns are
    frozen, but only up to ``MAX_CRITICAL_FULL`` keep their full body (Phase 4.1
    hard cap) — beyond that they degrade to a summary pointer.
    """

    step: int
    tool: str
    ok: bool
    exit_code: int
    path_hint: str
    summary: str
    output: str = ""
    evidence_id: str = ""
    critical: bool = False


@dataclass
class _LoopCtx:
    """Mutable, per-``run()`` loop state.

    Hoisted off the stack so single-responsibility helpers can read/write it
    without threading a dozen scalars through every call. Re-created on each
    ``run()`` call, so the loop stays re-entrant and stateless between runs.
    """

    user_prompt: str
    start_time: float = field(default_factory=time.time)
    last_command: Optional[ToolCall] = None
    repeated: int = 0
    self_correct_count: int = 0
    # Phase5 (GoalSpec): separate retry budget for goal-exit verification, so a
    # failing goal check re-enters the loop independently of the no-tool
    # self-correction counter.
    goal_correct_count: int = 0
    fingerprints: list[str] = field(default_factory=list)
    # Phase 4.5 — anti-frustration trackers:
    #  • Normalized web_search queries already executed this run (for dedup).
    executed_search_queries: list[str] = field(default_factory=list)
    #  • Most-recent web_search result text, keyed for cache-return on repeat.
    last_search_cache: dict[str, str] = field(default_factory=dict)
    #  • Consecutive reasoning rounds that produced NO new (dispatched) tool
    #    call. Reset to 0 whenever a real tool dispatch occurs.
    consecutive_no_tool_rounds: int = 0
    # Phase 8 (RAG Auto-Trigger): guards against re-triggering the forced
    # search_knowledge_base call more than once per run.
    rag_auto_triggered: bool = False
    # Session allowlist of approved shell commands (exact command string).
    # Cached for the duration of the current run() so repeated identical
    # commands don't re-prompt the operator. Never persisted across runs.
    approved_shell: set[str] = field(default_factory=set)
    # Phase4: ordered ring of completed tool turns. The last
    # _TOOL_WINDOW turns keep full output; older turns are compressed into
    # <past_steps_summary>. Critical-evidence turns are frozen regardless.
    tool_interactions: list[_ToolInteraction] = field(default_factory=list)
    # Phase 0 convergence: how many times a non-recursive root listing (`list .`)
    # has been allowed this run. Permitted exactly ONCE so the model can satisfy
    # the verifier's "directories explored >= 1" gate without re-scanning.
    root_list_count: int = 0
    # Phase 0 fix B: cumulative no-tool reasoning rounds that NEVER resets on a
    # transient tool call. The consecutive counter is reset by real dispatches
    # (which a small model can interleave to dodge the cap), so this cumulative
    # one is what actually bounds non-converging thought-only loops.
    total_no_tool_rounds: int = 0
