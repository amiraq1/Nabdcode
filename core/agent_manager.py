import os
from pathlib import Path
from smolagents import CodeAgent, ManagedAgent
from smolagents.tools import FinalAnswerTool

from core.tool_factory import build_skill_tools
from core.memory_manager import PersistentMemory
from tools.secure_tools import (
    SecureWorkspaceReader,
    SecureGitInspector,
    SecureSemanticMemoryTool,
    SecureFileSystemTool,
    SecureShellTool,
    SecureWebSearchTool,
    SecureBrowserTool,
    SecureCodeIntelligenceTool,
    SecurePythonREPLTool,
    SecureTasteManagerTool,
    SecureGraphifyTool,
)
from core.llm import get_secure_model
from core.parser import pin_workspace_root
from core.repo_scanner import SECURE_REPO_SCANNER
from core.adapters import _KernelSecurityEngine


# ── Phase 1: Spatial Awareness & Persona Injection (OpenCode DNA port) ──
_ENV_EXCLUDED_DIRS = {".git", "__pycache__", "node_modules"}
_ENV_EXCLUDED_PREFIXES = (".")
_ENV_EXCLUDED_SUFFIXES = (".gguf",)


def _workspace_tree(root: Path, max_depth: int = 2) -> str:
    """Lightweight directory tree excluding heavy/hidden dirs and .gguf files."""
    lines: list[str] = [root.name + "/"]

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = [c for c in d.iterdir() if not c.is_symlink()]
        except OSError:
            return
        dirs = sorted((c for c in children if c.is_dir()), key=lambda p: p.name.lower())
        files = sorted((c for c in children if c.is_file()), key=lambda p: p.name.lower())
        for c in dirs:
            if c.name in _ENV_EXCLUDED_DIRS or c.name.startswith(_ENV_EXCLUDED_PREFIXES):
                continue
            lines.append("    " * depth + c.name + "/")
            walk(c, depth + 1)
        for c in files:
            if c.suffix in _ENV_EXCLUDED_SUFFIXES:
                continue
            lines.append("    " * depth + c.name)

    walk(root, 1)
    return "\n".join(lines)


def get_workspace_env_block(workspace_path: str = ".") -> str:
    """Build an <env> block with a quick workspace directory tree.

    Mirrors OpenCode's runtime env-injection: grounds the model in the real
    directory layout. Uses only stdlib (os/pathlib) and excludes heavy/hidden
    dirs (.git, __pycache__, node_modules) and *.gguf model files.
    """
    try:
        from core.parser import get_workspace_root

        root = get_workspace_root()
    except Exception:
        root = Path(workspace_path).resolve()
    tree = _workspace_tree(root)
    return (
        "<env>\n"
        "Here is useful information about your workspace environment:\n"
        f"[Directory Tree]\n{tree}\n"
        "</env>"
    )


_BASE_PERSONA = (
    "You are NABD, a highly advanced local AI assistant operating within a "
    "Zero-Trust mobile architecture.\n"
    "CRITICAL RULE: You MUST answer ALL user queries strictly and exclusively in English. "
    "Never use Arabic or any other language in your responses, regardless of the user's input language.\n"
    "ORCHESTRATOR ROLE: You are the ORCHESTRATOR. You are STRICTLY FORBIDDEN from calling "
    "execute_shell. You must ALWAYS delegate code generation and system tasks to the CODER "
    "agent using the proper handoff mechanism (emit an agent_handoff with to_role='CODER'). "
    "Never emit an execute_shell tool call yourself; such calls are rejected by the security "
    "gate and will not execute.\n"
)

_PHASE1_DIRECTIVES = (
    "BEHAVIORAL DIRECTIVES (strictly enforced):\n"
    "1. CONCISENESS: Keep responses extremely concise - 4 lines or fewer whenever possible. "
    "Prefer one-word/one-line answers for direct questions. NEVER use preambles, greetings, "
    "or robotic AI apologies. Answer directly with no intro/outro.\n"
    "2. NO UNNECESSARY TOOLS: If the user provides a simple greeting (e.g., 'hi', 'hello', "
    "'how are you'), respond directly and conversationally. DO NOT invoke any tools.\n"
    "3. EXPLAIN BEFORE ACTING: Before triggering any tool call, briefly state what you are "
    "doing and why, in first person.\n"
    "4. FILE VS DIRECTORY: Never use `secure_workspace_reader` on a directory path. It is "
    "strictly for reading files. If you need to list directory contents, use `secure_shell` "
    "to execute `ls` or `tree`.\n"
    "5. SECRET HYGIENE: NEVER log, print, or output plain-text secrets, API keys, tokens, or "
    "credentials. Redact as '***' if reference is unavoidable. Never introduce code that "
    "exposes or commits secrets.\n"
)


def _build_system_prompt(workspace_path: str = ".") -> str:
    """Compose the Phase-1 system prompt with runtime env injection."""
    return _BASE_PERSONA + _PHASE1_DIRECTIVES + "\n" + get_workspace_env_block(workspace_path)



def initialize_secure_agent(workspace_path: str = ".") -> CodeAgent:
    model = get_secure_model()
    home = os.path.expanduser("~")
    allowed_roots = [
        os.path.join(home, "smart-agent"),
        os.path.join(home, "9router"),
    ]
    # Pin the workspace root so core.parser._validate_path enforces the jail
    # on the production (main.py) path, matching AppContext.build() behaviour.
    pin_workspace_root(Path(workspace_path).resolve())

    # 1. The Executor (The Hands) - Full, real-operation toolchain.
    # All tools are smolagents.Tool instances (with forward()) that delegate to
    # the hardened BaseTool.execute implementations (workspace jail + token clamps).
    executor_agent = CodeAgent(
        tools=[
            SecureWorkspaceReader(allowed_roots=allowed_roots),
            # SecureGitInspector(),    # 🛑 تم سحب الصلاحية (Tool Fixation guard)
            # SecureTestRunner(),      # 🛑 تم سحب الصلاحية (Tool Fixation guard)
            SecureSemanticMemoryTool(),
            # Real edit/exec capability so the Executor description is truthful.
            SecureFileSystemTool(workspace=workspace_path),
            SecureShellTool(security_engine=_KernelSecurityEngine()),
            SecureWebSearchTool(),
            SecureBrowserTool(workspace_dir=workspace_path),
            SecureCodeIntelligenceTool(workspace=workspace_path),
            SecurePythonREPLTool(workspace=workspace_path),
            SecureTasteManagerTool(workspace=workspace_path),
            SecureGraphifyTool(workspace_dir=workspace_path),
            # Read-only workspace map/search (excludes heavy dirs + .gguf).
            SECURE_REPO_SCANNER(),
            # Dynamically discovered skills (BaseSkill -> Tool via adapter).
            *build_skill_tools(),
        ],
        model=model,
        name="Executor",
        description=(
            "A surgical operator that interacts with the file system, searches the web, runs bash commands, runs Python scripts, manages taste rules, queries graph structure, and inspects code. "
            f"Can read files from these roots: {allowed_roots}. "
            "Use secure_file_system to read/write/edit files, secure_shell to run validated commands, secure_python_repl to execute Python code/math, secure_code_intelligence for AST symbol discovery, secure_taste_manager to remember coding rules/preferences, and secure_graphify_tool to query codebase relationships and knowledge graphs. "
            "IMPORTANT: secure_shell runs WITHOUT a shell, so redirection (>, >>) and chaining (&&, |) do NOT work. "
            "To CREATE OR WRITE a file, use secure_file_system with action='write' (or 'append'/'replace') and pass 'content' — never 'echo ... > file'. "
            "secure_shell is only for commands that print to stdout (e.g. 'pytest', 'grep', 'ls'). For Python snippets or calculations, use secure_python_repl — never secure_shell('python -c ...')."
        ),
        # Avoid cluttering the local-model context window with default smolagents tools.
        add_base_tools=False,
        # Loop guard: stop the Executor cleanly if it gets stuck (Termux-safe).
        max_steps=6,
        system_prompt=_build_system_prompt(workspace_path),
    )

    # Wrap it securely so the manager can call it.
    managed_executor = ManagedAgent(
        agent=executor_agent,
        name="system_executor",
        description=(
            "Use this agent to execute code, search the workspace, edit files, or run tests. "
            "Pass specific, actionable instructions. If it fails twice on the same task, stop and report the error."
        ),
    )

    # 2. The Manager (The Brain) - Orchestrates the workflow.
    manager_agent = CodeAgent(
        tools=[FinalAnswerTool()],  # Inject final-answer tool explicitly.
        model=model,
        managed_agents=[managed_executor],
        name="Manager",
        description=(
            "You are the lead planner. Break down user requests, delegate tasks to the system_executor, "
            "and synthesize the final report. ALWAYS return FinalAnswerTool when the task is complete."
        ),
        add_base_tools=False,
        # Loop guard for the planner.
        max_steps=5,
        system_prompt=_build_system_prompt(workspace_path),
    )

    # Memory store in workspace
    try:
        from tools.search_memory import SearchMemoryTool
        from engine.tool_registry import tool_registry
        memory_dir = Path(workspace_path) / ".nabd" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        search_memory = SearchMemoryTool(memory_dir)
        if "search_memory" not in tool_registry:
            tool_registry.register("search_memory", search_memory, profile="executor")
    except Exception:
        pass

    return manager_agent


# Process-wide memory store (fail-safe singleton). Verified tools and
# learned lessons persist across runs; a storage error never halts the OS.
MemoryStore = PersistentMemory()


_VERIFIER_PROMPT = (
    "You are the NABD Verification Gate. You receive an executor payload (code, "
    "config, or structured output) plus the original task. Evaluate it STRICTLY "
    "against two axes:\n"
    "1. SECURITY: no hardcoded secrets, no arbitrary exec of untrusted input, no "
    "path traversal outside the pinned workspace, no unsafe deserialization.\n"
    "2. STRUCTURE: it addresses the task, is syntactically valid, and follows the "
    "stated schema/contract.\n"
    "Respond ONLY with a JSON object on a single line, no prose:\n"
    '{"passed": true|false, "reasons": ["..."], "fix_hint": "..."}\n'
    "If passed is false, fix_hint MUST tell the executor exactly what to change."
)


def _build_verifier_agent(model) -> "CodeAgent":
    """Construct the dedicated Verifier prompt layer (LLM-as-judge)."""
    return CodeAgent(
        tools=[FinalAnswerTool()],
        model=model,
        name="Verifier",
        description="Strict security/structure verification gate for executor payloads.",
        add_base_tools=False,
        max_steps=3,
        system_prompt=_VERIFIER_PROMPT,
    )


def _broadcast(milestone: str, detail: str = "") -> None:
    """Emit a verification milestone through the safe UI bridge fan-out."""
    try:
        from core.ui_bridge import get_bridge

        get_bridge()._notify_observers("on_status_changed", f"VERIFY_{milestone}", detail)
    except Exception:
        # Bridge must never break the loop.
        pass


def execute_with_verification(task: str, max_retries: int = 3) -> dict:
    """Plan-Act-Verify loop: generate, verify, retry on rejection.

    Returns a status dict:
        {"status": "verified"|"failed", "final_payload": str,
         "attempts": int, "rejections": list}
    """
    model = get_secure_model()
    executor = initialize_secure_agent()
    verifier = _build_verifier_agent(model)

    # 1. Load historical memory and prepend as alignment context.
    lessons = MemoryStore.lessons_learned
    failures = MemoryStore.failure_logs
    context = ""
    if lessons:
        context += "LESSONS LEARNED (apply these):\n" + "\n".join(f"- {l}" for l in lessons) + "\n"
    if failures:
        context += "FAILURES TO AVOID (do NOT repeat):\n" + "\n".join(
            f"- {f['action']}: {f['error']}" for f in failures
        ) + "\n"

    aligned_task = (context + "\n---\nTASK:\n" + task).strip()

    rejections: list = []
    last_payload = ""
    status = "failed"

    for attempt in range(1, max_retries + 1):
        _broadcast("START", f"attempt {attempt}/{max_retries}")
        # 2. Executor generates the payload.
        last_payload = executor.run(aligned_task)

        # 3. Verifier evaluates it.
        _broadcast("EVALUATE", f"attempt {attempt}")
        verdict_raw = verifier.run(
            f"TASK:\n{task}\n\nEXECUTOR PAYLOAD:\n{last_payload}"
        )
        verdict = _parse_verdict(verdict_raw)

        if verdict["passed"]:
            _broadcast("SUCCESS", f"attempt {attempt}")
            status = "verified"
            # 4. Persist any fresh architectural insight gained this run.
            _persist_lesson_if_any(last_payload, task)
            break

        # Rejected: log failure, inject feedback, retry.
        reasons = "; ".join(verdict.get("reasons", []))
        rejections.append({"attempt": attempt, "reasons": reasons})
        MemoryStore.log_failure(f"verify:{task[:80]}", reasons)
        _broadcast("RETRY", f"attempt {attempt}: {reasons}")
        aligned_task = (
            f"PREVIOUS ATTEMPT REJECTED BY VERIFIER.\n"
            f"REASONS: {reasons}\n"
            f"FIX HINT: {verdict.get('fix_hint', '')}\n\n"
            f"{aligned_task}"
        )

    if status != "verified":
        _broadcast("EXHAUSTED", f"retries={max_retries}")

    return {
        "status": status,
        "final_payload": last_payload,
        "attempts": min(max_retries, len(rejections) + (1 if status == "verified" else 0)),
        "rejections": rejections,
    }


def _parse_verdict(raw: str) -> dict:
    """Extract {passed, reasons, fix_hint} from the verifier's JSON response."""
    import json
    import re

    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return {
                "passed": bool(data.get("passed", False)),
                "reasons": data.get("reasons", []),
                "fix_hint": data.get("fix_hint", ""),
            }
    except Exception:
        pass
    # Unparsable verdict: treat as rejection to stay conservative.
    return {"passed": False, "reasons": [f"unparsable verdict: {raw[:120]}"], "fix_hint": ""}


def _persist_lesson_if_any(payload: str, task: str) -> None:
    """Best-effort: if the payload reads like a non-trivial artifact, log it as a lesson."""
    try:
        if len(payload) > 50 and ("def " in payload or "class " in payload or "import " in payload):
            MemoryStore.add_lesson(f"Verified solution for: {task[:80]}")
    except Exception:
        pass
