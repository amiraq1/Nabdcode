"""Shared constants and small classification helpers for the agent."""

from typing import Final, Set, Tuple

# ── Chitchat detection ──────────────────────────────────────────────────────
#
# Heuristic set for quick prompt classification.  This is NOT a full NLU
# classifier — it only catches single-word / very short greetings and
# acknowledgements.  Any longer or more specific prompt is treated as
# substantive (require_tools=True → L1 verification applies).
#
# Rationale for keeping it small and explicit:
#   - Over-classifying as chitchat would let user-facing questions skip
#     verification, defeating the guardrail.
#   - Under-classifying is safe (the agent just spends one inference step
#     verifying trivial claims instead of chitchat-passing).
#   - Adding every possible cultural/regional greeting is a losing game;
#     genuine prompts with "Salam, analyze this project" are >1 token anyway.

CHITCHAT_SET: Final[Set[str]] = {
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay",
    "yes", "no", "exit", "quit", "clear", "bye", "goodbye",
    "sup", "yo", "thanks!", "ok!", "yes!", "no!",
    "iraq", "مرحبا", "مرحبا!", "أهلا", "أهلا!", "هلا", "سلام",
}

HARD_RULES: Final[str] = """
[RULES - VERIFIER CONTRACT]
1. STRICTLY FORBIDDEN: Numerical claims ("found", "there are", "total", count) without a verbatim quote from tool output between backticks.
2. If asked "how many" / "count", you MUST call file_system.read first, then count from the command output.
3. If the task is simple chitchat (e.g. 'iraq' or greetings), answer directly with no tools and no request for evidence.
"""



def is_chitchat(text: str) -> Tuple[bool, str]:
    """Classify a user prompt as chitchat (True) or substantive (False).

    Returns (is_chitchat: bool, reason: str).
    """
    lower = text.lower().strip()
    if not lower:
        return True, "empty input"
    if lower in CHITCHAT_SET:
        return True, f"recognised chitchat token '{lower}'"
    return False, "substantive or multi-word"


SAFE_BINARIES: Final[Set[str]] = {
    "ls", "pwd", "echo", "whoami", "cat", "grep", "date", 
    "ps", "uptime", "df", "free", "history", "clear", "find", "wc",
    "du", "sort", "head", "tail", "awk", "top",
    "termux-battery-status", "termux-telephony-deviceinfo",
    "git", "python", "python3", "uname", "id",
    "sleep", "lsof", "pytest"
}

DANGEROUS_STRICT: Final[Set[str]] = {";", "`", "$("}
TODO_DISCIPLINE: Final[str] = """
## TODO Discipline (Mandatory)

When working on a multi-step task, you MUST use the `todo_write` tool as follows:

1. **Before starting**, call `todo_write(action="plan", items=[...])` with the full list of steps you intend to take. Do this even for tasks that seem simple if they involve more than one file or more than one verification step.

2. **Before starting a step**, call `todo_write(action="update", item_id=N, status="in_progress")`.

3. **Before marking a step "done"**, you MUST have actually run a verification command for that step's specific claim — not assumed it, not inferred it from writing the code. Verification means one of:
   - Running `python3 -m py_compile <file>` (or equivalent) and observing zero errors in the raw output
   - Running a search (grep or equivalent) for stale references and observing the actual result
   - Running the actual code path and observing real output that confirms the claim
   - Running the project's test suite and observing pass/fail counts in raw output

4. **The verification_note you pass to `todo_write` must quote or closely paraphrase the actual command output you observed** (e.g., "py_compile: 0 errors on 4 files" or "grep for 'search_memory': no matches"). A vague note like "tested and works" will be treated as insufficient evidence.

5. **If verification fails**, do NOT mark the step done. Report the failure explicitly to the user, keep the item as `in_progress` or add a new item describing the fix needed, and continue.

6. You may not claim a task is complete in your final response unless every TODO item's status is "done" with a verification_note behind it.
"""

SECURITY_COMPLIANCE_RULE: Final[str] = """
## Security Compliance Policy
SECURITY COMPLIANCE RULE: If a tool execution fails with a "security validation error" or a whitelist rejection, do not attempt to bypass it or invoke semantic memory for a workaround. Inform the user directly that the command is restricted by the secure execution policy.
"""

LANGUAGE_POLICY: Final[str] = """
## Language & Communication Policy (Mandatory)
- Every visible response MUST be written exclusively in fluent, professional English.
- Treat Arabic solely as an input language. Never generate Arabic text unless explicitly requested by the user.
- All explanations, code, comments, logs, status messages, plans, reports, TODOs, commit messages, documentation, and examples MUST be in English.
"""

PYTHON_AND_CODE_EXPLORATION_POLICY: Final[str] = """
## Python Execution & Code Intelligence Policy (Mandatory)
1. **Executing Python Code**: To execute Python snippets, math calculations, data analysis, or logic verification, you MUST use the `python_repl` (`secure_python_repl`) tool. NEVER use `execute_shell` (`secure_shell`) to run `python -c ...` or `python3 -c ...` (which is blocked by kernel security).
2. **Exploring Code & Definitions**: To list classes/methods or locate definitions in Python files, you MUST use the `code_intelligence` (`secure_code_intelligence`) tool with actions `list_symbols` or `get_definition`. NEVER use blind full-file reading or raw `grep` for structure discovery when `code_intelligence` can provide precise AST symbol mapping.
3. **No Hallucination on Gate Rejections**: If a command or tool call is rejected by kernel security or validation, do NOT invent or fabricate execution results. Report the block or switch to the appropriate dedicated tool (`python_repl` or `code_intelligence`).
"""

GRAPHIFY_KNOWLEDGE_GRAPH_POLICY: Final[str] = """
## Graphify Knowledge Graph Policy (Mandatory)
For any question about this repo's architecture, structure, components, or how to add/modify/find code, your first action MUST be `graphify_tool` with action="query" and target="<question>" when graphify-out/graph.json exists.

Triggers: "how do I…", "where is…", "what does … do", "add/modify a ", "explain the architecture", or anything that depends on how files or classes relate.

Rules:
1. Use action="query" and target="<question>" for general structure discovery.
2. Use action="path" for relationships between <A> and <B>.
3. Use action="explain" for focused concepts.
These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
4. If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
5. Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
6. Only read source files when (a) modifying/debugging specific code, (b) the graph lacks the needed detail, or (c) the graph is missing or stale.
7. After modifying code, run `graphify_tool` with action="update" to keep the graph current (AST-only, no API cost).
"""


