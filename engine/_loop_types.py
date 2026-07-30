from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Optional

from core.parser import ToolCall
from core.prompts import BROWSER_FEWSHOT_EXAMPLES, CRITICAL_RULES_FOR_TOOL_CALLING


# ── Shared loop constants (consumed by context + dispatch mixins) ────────────
TOOL_WINDOW: Final[int] = 2
CHAT_WINDOW: Final[int] = 12
MAX_CRITICAL_FULL: Final[int] = 3

# Budget / anti-frustration ceilings (extracted from loop.py, refactor step5-c).
# Module-local to the engine loop — no external references — so they live here
# alongside the other shared loop constants.
MAX_BUDGET_SECONDS: Final[int] = 180  # سقف الميزانية: 3 دقائق لكل مهمة على Termux
MAX_BUDGET_TOKENS: Final[int] = 12000  # سقف التوكنات التقريبي
MAX_CONSECUTIVE_NO_TOOL_ROUNDS: Final[int] = 3  # legacy reasoning-count cap (superseded)
# Loop progress accounting (root fix — no-progress semantics):
# the loop aborts only after this many consecutive iterations that produced NO
# substantive new evidence. Genuine stalls (repeated identical calls, TODO-only
# churn, failed dispatches) still terminate; productive runs reset the counter.
MAX_NO_PROGRESS_STEPS: Final[int] = 3
BUDGET_SOFT_WARN_RATIO: Final[float] = 0.80  # final 20% of budget is reserved for synthesis/finalization

# ── IntentPolicy (PATCH-CORE-UNIFIED-R3) ────────────────────────────────────
# Single source of truth for how an intent maps to convergence and read-count
# requirements. Created once per run from classify_intent() and stored on _LoopCtx.


@dataclass
class IntentPolicy:
    """Convergence policy derived from a single ``classify_intent()`` call.

    Attributes:
        requires_plan:  When True, a CompletionTracker must be present before
                        finalization is allowed (fail-closed).
        minimum_reads:  Minimum distinct file reads required before a final
                        answer may be emitted. Applied upfront — NOT as a
                        post-hoc hack.
        needs_investigation: When True, the prompt requires tool-using
                        investigation rather than chitchat.
    """

    requires_plan: bool = False
    minimum_reads: int = 0
    needs_investigation: bool = False


# Prompt Leak Markers — shared between streaming and non-streaming paths.
# Detects structural system markers leaked in model output and triggers
# provider failover instead of displaying them to the user.
_LEAK_MARKERS: Final[frozenset[str]] = frozenset({
    "## TODO Discipline",
    "<hard_rules>",
    "<system_instructions>",
    "<system_identity>",
    "CRITICAL RULE:",
    "TASK CLASSIFICATION",
    "SMALL-TALK & CHIT-CHAT PROTOCOL",
})

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


class _LoopPhase(Enum):
    """Explicit turn-lifecycle state machine for progress accounting.

    ``PLAN -> COLLECT -> SYNTHESIZE -> FINALIZE``. Transitions are monotone:
    once SYNTHESIZE begins (budget reserve, no-progress cap, or finalizing
    guard), the loop never returns to planning/collection; FINALIZE is
    terminal. string values keep ``_LoopCtx.phase`` JSON/debug friendly.
    """

    PLAN = "PLAN"
    COLLECT = "COLLECT"
    SYNTHESIZE = "SYNTHESIZE"
    FINALIZE = "FINALIZE"


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
    #    DEPRECATED (superseded by consecutive_no_progress below); kept for
    #    external/test compatibility — the engine no longer increments it.
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
    # ── PATCH-CORE-UNIFIED-R3: intent + policy (single classification) ──
    # Set once in run() via classify_intent(). NEVER re-classified dynamically.
    intent: str = "Chat"
    intent_policy: IntentPolicy = field(default_factory=IntentPolicy)
    # Phase 0 fix B: cumulative no-tool reasoning rounds that NEVER resets on a
    # transient tool call. DEPRECATED (superseded by consecutive_no_progress
    # + the step/budget hard ceilings) — the engine no longer increments it.
    total_no_tool_rounds: int = 0
    # ── Loop progress accounting (no-progress semantics, root fix) ─────────
    # Explicit FSM phase: "PLAN" -> "COLLECT" -> "SYNTHESIZE" -> "FINALIZE"
    # (see _LoopPhase). Monotone — never moves backwards.
    phase: str = "PLAN"
    # Separate counters: total steps live in state.step_count; dispatched
    # tool iterations in tool_call_count; consecutive progress-free
    # iterations in consecutive_no_progress.
    tool_call_count: int = 0
    consecutive_no_progress: int = 0
    # Fingerprints of (tool, args, output) triples that produced NEW
    # evidence this run. An identical call+result fingerprint hit is NOT
    # progress (invariant 5); a miss resets the no-progress counter (6).
    progress_sigs: set[str] = field(default_factory=set)
    # Signature of the most recent todo_write payload. An identical repeat
    # is suppressed BEFORE tool execution (invariant 4).
    last_todo_sig: str = ""
