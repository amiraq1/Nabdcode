"""
_loop_helpers — module-level pure helpers + constants for engine/loop.py.

Extracted from engine/loop.py (refactor step6 — P0.2 decomposition) to shrink
the god-module. These are zero-state pure functions (no ExecutionLoop instance
required) plus the module-level constants they share. The ExecutionLoop class
re-imports them from here so the public surface (``from engine.loop import
_prompt_requires_investigation`` etc.) is preserved byte-for-byte for callers
and tests.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Final

from core.constants import is_chitchat
from engine.interfaces import DispatcherProtocol
from engine.state import RuntimeState


# ---------------------------------------------------------------------
# Phase 2: Dynamic Few-Shot for small / fallback models
# ---------------------------------------------------------------------
#
# Small or local fallback models (e.g. "gemma-2-9b-it", "mini", "local") tend to
# wrap tool calls in prose or markdown fences. A tight few-shot anchor showing
# the exact one-line JSON shape measurably reduces those hallucinations. It is
# only injected when the active model is detected as a small/fallback tier so we
# never bloat the context for capable models.

_SMALL_FALLBACK_MODEL_KEYWORDS: Final[tuple[str, ...]] = (
    "9b", "8b", "mini", "fallback", "local",
)


def _prompt_requires_investigation(text: str, has_active_goal: bool = False) -> bool:
    """Return True if this prompt asks for real work, not chitchat, simple math, or casual/informational chat."""
    if has_active_goal:
        return True
    from core.investigation import classify_intent, is_multi_stage_investigation
    if is_multi_stage_investigation(classify_intent(text)):
        return True
    if is_chitchat(text)[0]:
        return False
    if re.search(r'^\s*\d+\s*[\+\-\*\/]\s*\d+', text):
        return False

    lower = text.lower().strip()
    workspace_targets = (
        "this project", "this repo", "this code", "this file", "in /",
        "file", "files", "directory", "dir", "folder", "codebase", "workspace",
        "repo", "project", ".py", ".js", ".md", ".json", ".txt", ".sh",
        "todo", "pytest", "tests", "error in", "bug in", "log", "logs",
        "ls ", "grep ", "cat ", "sed ", "git ",
        "مستودع", "الكود", "كود", "ملف", "ملفات", "مجلد", "المشروع", "مشروع", "سجل", "سجلات", "الشيفرة",
    )
    workspace_actions = (
        "analyze", "check ", "find ", "read ", "list ", "search ", "run ",
        "execute ", "test ", "debug ", "fix ", "edit ", "write ", "create ",
        "modify ", "update ", "delete ", "count ", "how many", "show ",
        "scan ", "build ", "compile ", "inspect ",
        "افحص", "فحص", "حلل", "حلّل", "دقق", "دقّق", "راجع", "شغل", "شغّل", "نفذ", "نفّذ", "اقرأ", "ابحث", "اعرض", "صحح", "صحّح", "اصلح", "أصلح", "عدل", "عدّل", "انشئ", "أنشئ", "احسب",
    )
    if any(target in lower for target in workspace_targets) or any(lower.startswith(act) or f" {act}" in lower for act in workspace_actions):
        return True

    informational_prefixes = (
        "explain ", "what is ", "what are ", "what's ", "how does ",
        "how do ", "tell me ", "why does ", "why is ", "why do ",
        "summarize ", "define ", "compare ", "describe ", "can you explain ",
        "could you explain ", "difference between ", "explain the difference ",
    )
    if any(lower.startswith(pref) or pref in lower for pref in informational_prefixes):
        return False

    # Default: لا إشارة عمل/مستودع -> محادثة/معرفة عامة
    return False


# Strip a leading "Thought for Ns" prefix so the replication fingerprint ignores
# varying think-times that would otherwise evade the repetition guard.
_THOUGHT_PREFIX_RE = re.compile(
    r"^(?:\s*[\*\-]\s*)?(?:Thought|Thinking)\s+(?:for\s+\d+\s*(?:s|seconds?)|through|about)\s*",
    re.IGNORECASE,
)


def _normalize_response(response_text: str) -> str:
    """Strip leading 'Thought for Ns' and `<think>...</think>` blocks from a response."""
    text = re.sub(r"<(?:think|thought)>.*?</(?:think|thought)>", "", response_text, flags=re.IGNORECASE | re.DOTALL)
    return _THOUGHT_PREFIX_RE.sub("", text).strip()


def _extract_cmd_or_path(tool_args: Any) -> str:
    """Extract a clean target path or command summary from tool arguments."""
    if not isinstance(tool_args, dict):
        return str(tool_args)[:60]
    return str(
        tool_args.get("command")
        or tool_args.get("path")
        or tool_args.get("file_path")
        or tool_args.get("AbsolutePath")
        or tool_args.get("SearchPath")
        or tool_args.get("TargetFile")
        or tool_args.get("file")
        or tool_args.get("query")
        or str(tool_args)[:60]
    )


def _extract_final_answer(raw_json: str | None) -> str | None:
    """Detect a smolagents-style final_answer tool call and return its answer.

    The casual-chat system prompt instructs the model to conclude directly with
    ``final_answer`` (a real smolagents termination convention). ``final_answer``
    is intentionally NOT registered as a tool (it is not an executable tool), so the
    schema gate would reject it as "Unknown tool" and force the model
    into a correction/explain loop on a simple greeting. We detect it explicitly
    here and return the answer text so the loop can terminate cleanly.

    Returns the answer string, or ``None`` if the payload is not a final_answer.
    """
    if not raw_json:
        return None
    try:
        obj = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("tool") != "final_answer":
        return None
    args = obj.get("args") or {}
    answer = args.get("answer") if isinstance(args, dict) else None
    if not isinstance(answer, str):
        return None
    return answer.strip()


def _looks_like_tool_call(text: str) -> bool:
    """True when ``text`` is (or contains) a raw tool-call JSON — e.g. the last
    model response was another tool invocation rather than a synthesized report.

    Matches a bare ``{...}`` payload AND one wrapped in prose / a ```json fence,
    since the model's final output at the step ceiling is often fenced or
    prefixed with commentary. Used by the final-answer guard: a raw tool call
    sitting in ``_last_response`` must NOT be treated as a finished answer, or
    the run will dump that JSON as the "final answer".
    """
    if not text:
        return False
    stripped = text.strip()
    candidates = [stripped]
    # Extract fenced blocks: ```json ... ``` or ``` ... ```
    for m in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        candidates.append(m)
    # Fallback: first balanced-ish {...} object anywhere in the text.
    brace = text.find("{")
    if brace != -1:
        candidates.append(text[brace:])
    for cand in candidates:
        cand = cand.strip()
        if not cand.startswith("{"):
            continue
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            # Try up to the last closing brace if trailing prose exists.
            end = cand.rfind("}")
            if end != -1:
                try:
                    obj = json.loads(cand[: end + 1])
                except (json.JSONDecodeError, TypeError):
                    continue
            else:
                continue
        if isinstance(obj, dict) and "tool" in obj:
            return True
    return False


def _is_thought_only(response_text: str) -> bool:
    """True when the response is pure 'thinking' with no actionable content.

    Used by the blind-loop guard to abort on the first occurrence, before the
    model can spin an infinite no-progress loop.
    """
    normalized = _normalize_response(response_text)
    if len(normalized) < 10:
        return True
    return any(p.search(response_text.strip()) for p in FORBIDDEN_THOUGHT_PATTERNS)


MAX_SELF_CORRECT: Final[int] = 3
MAX_PROVIDER_FAIL_STREAK: Final[int] = 3
FALLBACK_ALLOWED_TOOLS: Final[set[str]] = {"final_answer", "search_memory", "todo_write"}

# Phase 4.5 — anti-frustration guards observed in live sessions:
#  • Cap consecutive reasoning rounds that produce NO new tool call. After this
#    many thought-only turns the model is forced to commit (tool call or a
#    clarification/final answer) instead of spinning silently.
#  • When the run has consumed this fraction of its budget ceiling, force the
#    agent to emit a partial/summary answer rather than dying silently at the
#    hard cap with nothing shown to the user.

# Phase4: in casual chat (no active goal) the compaction engine must still
# surface the recent conversation, not just the frozen first user prompt. This
# is the number of trailing raw chat messages (user + assistant turns, after the
# system message) retained so the latest question is never displaced by a stale
# greeting. Tool-driven runs keep their own (tool-interaction) window instead.
CHAT_WINDOW: Final[int] = 12


def _has_active_goal(self) -> bool:
    """True when a verifiable GoalSpec with success criteria is active.

    Mirrors the ``has_active_goal`` test used by ``_inject_runtime_context``:
    a goal only "counts" once it carries non-empty ``success_criteria`` (a
    goal with no criteria is treated as casual/chat). When False, the
    compaction/pruning logic must NOT freeze the original user prompt.
    """
    goal = getattr(self.state, "active_goal", None) if hasattr(self, "state") and self.state else None
    if goal is None:
        return False
    crit = getattr(goal, "success_criteria", None)
    return bool(crit) and str(crit) != "None"
TOOL_WINDOW: Final[int] = 2

# Phase4.1: hard cap on full-body critical evidence retained in context.
# Beyond this many critical entries, older critical items degrade gracefully to
# a structured summary pointer: [evidence:E-id] + summary (no raw output).
MAX_CRITICAL_FULL: Final[int] = 3

# Patterns that mark a response as "thinking-only" (no actionable tool call).
# Anchored at the start; tolerate leading bullet/star and trailing period.
FORBIDDEN_THOUGHT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*(?:[\*\-]\s*)?(?:Thought|Thinking)\s+(?:for\s+\d+\s*(?:s|seconds?)|through|about|process)\s*\.?$", re.IGNORECASE),
    re.compile(r"^\s*(?:[\*\-]\s*)?(?:I am thinking|I will think|I will now think|Let me think|Let's think)\s*\.?$", re.IGNORECASE),
    re.compile(r"^\s*(?:[\*\-]\s*)?Thinking through the problem\s*\.?$", re.IGNORECASE),
    re.compile(r"^\s*(?:[\*\-]\s*)?Proceeding to think\s*\.?$", re.IGNORECASE),
    re.compile(r"^\s*I will now think about that\s*\.?$", re.IGNORECASE),
    re.compile(r"^\s*<(?:think|thought)>.*</(?:think|thought)>\s*$", re.IGNORECASE | re.DOTALL),
)


def _resolve_default_provider() -> Callable[[list[dict[str, Any]], Any], str]:
    """Lazily resolve the default LLM provider.

    Imported at call time to avoid a circular import:
    engine/__init__ -> engine.loop -> llm_router -> core -> core.kernel.events
    would otherwise re-enter engine/__init__ mid-import.
    """
    from llm_router import execute_agent_with_memory
    return execute_agent_with_memory


def _resolve_default_verifier() -> Callable[[str, str, str, Any], str]:
    """Lazily resolve the independent verifier LLM (step6 DI seam).

    Mirrors ``_resolve_default_provider``: imported at call time to keep the
    engine.loop import graph acyclic (engine.loop -> llm_router -> core).
    """
    from llm_router import run_verifier_check
    return run_verifier_check


def _build_dispatcher(state: RuntimeState) -> "DispatcherProtocol":
    """Lazily construct the concrete Dispatcher.

    Kept out of the module-level import chain so importing ``engine.loop`` never
    forces ``engine.dispatcher`` (and its ``engine.tool_registry`` /
    ``tools.base`` subgraph) to load first. This is the DI seam that breaks the
    loop<->dispatcher<->registry<->parser import cycle at its root.
    """
    from engine.dispatcher import Dispatcher
    return Dispatcher(state)


def _derive_read_hint(user_prompt: str) -> str:
    """Extract a path-like term from the user prompt for the rejection directive.

    Scans the user prompt for path-like patterns (directory names, file paths,
    keywords like 'core', 'engine', 'src', etc.) and returns a suggestion like
    ' (e.g. file_system.read path=core/__init__.py)'. Returns empty string when
    no hint can be derived so the rejection message stays clean for chitchat.
    """
    if not user_prompt:
        return ""
    # Known workspace directories (project-specific, not hardcoded as mandatory)
    _known = ("core", "engine", "tools", "ui", "tests", "scripts", "src", "lib")
    _lower = user_prompt.lower()
    for kw in _known:
        if kw in _lower:
            m = re.search(re.escape(kw), user_prompt, re.IGNORECASE)
            if m:
                return f" (e.g. {m.group()}/__init__.py)"
    return ""


def _type_name(t: Any) -> str:
    """Map a Python type annotation to a short human-readable name."""
    if t is str:
        return "str"
    if t is int:
        return "int"
    if t is float:
        return "float"
    if t is bool:
        return "bool"
    if t is list:
        return "list"
    if t is dict:
        return "dict"
    name = getattr(t, "__name__", str(t))
    return name
