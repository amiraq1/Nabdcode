from typing import Final, Set

SAFE_BINARIES: Final[Set[str]] = {
    "ls", "pwd", "echo", "whoami", "cat", "grep", "date", 
    "ps", "uptime", "df", "free", "history", "clear", "find", "wc",
    "du", "sort", "head", "tail", "awk", "top",
    "termux-battery-status", "termux-telephony-deviceinfo",
    "git", "xargs", "python", "python3", "pip", "uname", "id", "env",
    "uvicorn", "curl", "wget", "sleep", "kill", "pkill", "lsof", "pytest",
    "node", "npm", "npx", "nohup", "bash", "sh", "setsid", "killall"
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
