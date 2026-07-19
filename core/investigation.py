"""Investigation workflow control, intent classification, coverage tracking, and completion gates.

Enforces goal-driven repository exploration over single-observation premature completion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, FrozenSet


# ── PHASE 1 — Investigation Intent Classification ──────────────────────────

class InvestigationIntent(str, Enum):
    CHAT = "Chat"
    SINGLE_FILE_LOOKUP = "Single File Lookup"
    TOOL_EXECUTION = "Tool Execution"
    REPOSITORY_INVESTIGATION = "Repository Investigation"
    ARCHITECTURE_REVIEW = "Architecture Review"
    CODE_AUDIT = "Code Audit"
    BUG_INVESTIGATION = "Bug Investigation"
    REFACTORING_REVIEW = "Refactoring Review"
    SECURITY_REVIEW = "Security Review"
    PERFORMANCE_REVIEW = "Performance Review"


MULTI_STAGE_INTENTS: FrozenSet[str] = frozenset({
    InvestigationIntent.REPOSITORY_INVESTIGATION,
    InvestigationIntent.ARCHITECTURE_REVIEW,
    InvestigationIntent.CODE_AUDIT,
    InvestigationIntent.BUG_INVESTIGATION,
    InvestigationIntent.REFACTORING_REVIEW,
    InvestigationIntent.SECURITY_REVIEW,
    InvestigationIntent.PERFORMANCE_REVIEW,
})


def classify_intent(user_prompt: str) -> str:
    """Classify the user prompt into one of the investigation/capability classes."""
    if not user_prompt:
        return InvestigationIntent.CHAT

    lower = user_prompt.lower().strip()

    # Chat / informational / simple check
    if any(lower.startswith(prefix) for prefix in ("hello", "hi", "hey", "thanks", "thank you", "good morning", "good evening", "how are you", "مرحبا", "أهلا", "اهلا", "السلام", "شكرا", "كيف حالك", "صباح", "مساء")):
        return InvestigationIntent.CHAT

    # Security Review
    if any(k in lower for k in ("security", "vulnerability", "vulnerabilities", "audit security", "cve", "injection", "xss", "auth flaw")):
        return InvestigationIntent.SECURITY_REVIEW

    # Performance Review
    if any(k in lower for k in ("performance", "optimize", "optimization", "latency", "bottleneck", "memory leak", "profile ", "profiling")):
        return InvestigationIntent.PERFORMANCE_REVIEW

    # Bug Investigation
    if any(k in lower for k in ("bug in", "error in", "traceback", "exception", "crash", "failing test", "why is it failing", "debug ")):
        return InvestigationIntent.BUG_INVESTIGATION

    # Refactoring Review
    if any(k in lower for k in ("refactor", "clean up", "cleanup", "technical debt", "restructure", "code smell")):
        return InvestigationIntent.REFACTORING_REVIEW

    # Code Audit / Repository Investigation / Architecture Review
    if any(k in lower for k in ("architecture", "system design", "design pattern", "explain the architecture", "how does the system work")):
        return InvestigationIntent.ARCHITECTURE_REVIEW

    if any(k in lower for k in ("inspect the repository", "inspect repository", "analyze the codebase", "analyze codebase", "review the project", "review project", "audit the repository", "audit repository", "explore the codebase", "explore codebase", "code audit", "repository structure", "repo structure")):
        return InvestigationIntent.REPOSITORY_INVESTIGATION

    if any(k in lower for k in ("audit", "review code", "code review", "check entire repo", "check the repository")):
        return InvestigationIntent.CODE_AUDIT

    # Single File Lookup
    if re.search(r"^(?:read|view|show|cat|check|inspect)\s+[\w/\-\.]+\.\w+$", lower):
        return InvestigationIntent.SINGLE_FILE_LOOKUP

    # Tool Execution / Specific target actions
    if any(lower.startswith(act) or f" {act} " in lower for act in ("run ", "execute ", "test ", "compile ", "build ", "pytest ", "git ")):
        return InvestigationIntent.TOOL_EXECUTION

    # If it asks broadly about the workspace/repo/project without specifying a single file
    if any(k in lower for k in ("repo", "repository", "codebase", "project", "workspace", "directory structure", "مستودع", "الكود", "المشروع", "الشيفرة", "الريبو", "افحص", "فحص", "حلل", "حلّل", "راجع", "دقق", "دقّق")):
        return InvestigationIntent.REPOSITORY_INVESTIGATION

    return InvestigationIntent.TOOL_EXECUTION


def is_multi_stage_investigation(intent: str) -> bool:
    """Return True if the classified intent requires a goal-driven multi-stage execution plan."""
    return intent in MULTI_STAGE_INTENTS


# ── PHASE 2 — Mandatory Investigation Plan ─────────────────────────────────

MANDATORY_INVESTIGATION_PLAN: List[str] = [
    "Discover repository structure",
    "Identify project type",
    "Locate entry points",
    "Locate build configuration",
    "Identify major modules",
    "Inspect representative files",
    "Collect evidence",
    "Generate final report",
]


# ── PHASE 5 — Investigation Progress State ─────────────────────────────────

class InvestigationProgressState(str, Enum):
    IDLE = "IDLE"
    DISCOVERING = "DISCOVERING"
    MAPPING = "MAPPING"
    ANALYZING = "ANALYZING"
    VERIFYING = "VERIFYING"
    REPORTING = "REPORTING"


# ── PHASE 4 & PHASE 7 — Evidence Coverage & Heuristics ─────────────────────

@dataclass
class CoverageMetrics:
    """Quantitative tracking of repository exploration coverage."""
    directories: int = 0
    modules: int = 0
    files: int = 0
    entrypoints: int = 0
    configuration: int = 0
    tests: int = 0
    architecture: int = 0
    inspected_paths: Set[str] = field(default_factory=set)

    @classmethod
    def from_records(cls, records: List[Any]) -> CoverageMetrics:
        metrics = cls()
        metrics.update(records)
        return metrics

    def update(self, records: List[Any]) -> None:
        """Derive coverage metrics from tool execution records."""
        dirs_set: Set[str] = set()
        modules_set: Set[str] = set()
        files_set: Set[str] = set()
        entrypoints_set: Set[str] = set()
        config_set: Set[str] = set()
        tests_set: Set[str] = set()
        arch_set: Set[str] = set()

        # Known configuration patterns
        config_patterns = (
            "pyproject.toml", "setup.py", "package.json", "makefile", "dockerfile",
            "cargo.toml", "go.mod", "pom.xml", "build.gradle", "requirements.txt",
            "config.py", "settings.py", "tox.ini", ".env", "tsconfig.json",
        )
        # Known entry point patterns
        entrypoint_patterns = (
            "main.py", "app.py", "__main__.py", "index.js", "index.ts", "cli.py",
            "run.py", "server.py", "wsgi.py", "asgi.py", "manage.py",
        )

        for r in records:
            if not getattr(r, "success", False):
                continue

            tool = getattr(r, "tool_name", getattr(r, "tool", ""))
            cmd_or_path = str(getattr(r, "input", getattr(r, "command_or_path", "")))
            out = str(getattr(r, "raw_output", getattr(r, "output_snippet", "")))

            # Directories discovered — covers both legacy list tools
            # (list_dir/find_files/execute_shell with 'ls'/'find') AND the
            # modern file_system tool, which records a directory path (e.g. "."
            # or "core") as command_or_path on a list action. A path with no
            # file extension and not a known file name is treated as a directory
            # so the verifier's "directories explored >= 1" gate can be satisfied
            # by a single non-recursive `list .` — the exact path Guard 4 permits.
            is_list_tool = tool in ("list_dir", "find_files", "file_system", "execute_shell") and (
                "ls" in cmd_or_path or "find" in cmd_or_path or "list" in tool or "find" in tool
            )
            _base = cmd_or_path.strip().split(" ")[0].strip("/").split("/")[-1]
            _looks_like_dir = (
                cmd_or_path.strip() in (".", "/")
                or cmd_or_path.rstrip().endswith("/")
                or (tool == "file_system" and "." not in _base and _base != "")
            )
            if is_list_tool or _looks_like_dir:
                dirs_set.add(cmd_or_path)
                if _base and not _base.startswith("."):
                    modules_set.add(_base)
                for line in out.splitlines():
                    clean_line = line.strip().split()[-1] if line.strip() else ""
                    if clean_line.endswith("/") or "/" in clean_line:
                        top_dir = clean_line.strip("/").split("/")[0]
                        if top_dir and not top_dir.startswith("."):
                            dirs_set.add(top_dir)
                            modules_set.add(top_dir)

            # Files read / inspected — ONLY genuine read/edit actions count as
            # "file inspection". A `list` action (directory listing) is NOT a
            # file read even if it targets a path, otherwise the verifier would
            # accept a bare `list .` as satisfying "files >= 3" (the exact
            # convergence failure observed live: the model listed directories
            # and the verifier accepted zero actual reads). We read the action
            # from the record when present, else infer from legacy tool names.
            rec_action = str(getattr(r, "action", "") or "").lower()
            is_read_action = (
                rec_action in ("read", "replace", "append", "edit", "edit_file", "view")
                or tool in ("view_file", "read_file", "grep_search")
                or (tool in ("code_intelligence", "secure_code_intelligence") and rec_action in ("list_symbols", "get_definition", "find_references"))
            )
            if is_read_action:
                clean_path = cmd_or_path.strip().split(" ")[0].replace("file://", "")
                if clean_path and ("/" in clean_path or "." in clean_path):
                    if not any(clean_path.endswith(ext) for ext in (".jpg", ".png", ".pdf")):
                        files_set.add(clean_path)
                        self.inspected_paths.add(clean_path)

                        lower_path = clean_path.lower()
                        # Configuration check
                        if any(lower_path.endswith(cp) or cp in lower_path for cp in config_patterns):
                            config_set.add(clean_path)
                        # Entry point check
                        if any(lower_path.endswith(ep) or ep in lower_path for ep in entrypoint_patterns):
                            entrypoints_set.add(clean_path)
                        # Tests check
                        if "test_" in lower_path or "_test.py" in lower_path or "tests/" in lower_path:
                            tests_set.add(clean_path)
                        # Module check
                        parts = clean_path.strip("/").split("/")
                        if len(parts) > 1 and not parts[0].startswith("."):
                            modules_set.add(parts[0])
                        # Architecture check
                        if any(k in lower_path for k in ("architecture", "readme", "design", "core/", "engine/")):
                            arch_set.add(clean_path)

        self.directories = len(dirs_set)
        self.modules = len(modules_set)
        self.files = len(files_set)
        self.entrypoints = len(entrypoints_set)
        self.configuration = len(config_set)
        self.tests = len(tests_set)
        self.architecture = len(arch_set)

    def is_sufficient_for_investigation(self) -> tuple[bool, List[str]]:
        """Evaluate if coverage satisfies Phase 3 & Phase 4 mandatory completion gates."""
        missing: List[str] = []
        if self.directories < 1:
            missing.append("Repository structure not discovered (directories explored = 0). Must run list_dir / find_files.")
        if self.configuration < 1:
            missing.append("Build configuration not located/inspected (e.g., pyproject.toml, package.json, setup.py, Makefile).")
        if self.entrypoints < 1 and self.modules < 1:
            missing.append("Entry point(s) and major modules not located (e.g., main.py, core/, engine/).")
        if self.files < 3:
            missing.append(f"Insufficient file inspection coverage (inspected {self.files} file(s), minimum required is >= 3 representative source files across modules).")

        return (len(missing) == 0, missing)


# ── PHASE 5 — State Machine & PHASE 3 / PHASE 8 / PHASE 9 Verification ───

def compute_investigation_state(coverage: CoverageMetrics) -> InvestigationProgressState:
    """Compute current investigation progress state based on coverage metrics."""
    if coverage.directories == 0 and coverage.files == 0:
        return InvestigationProgressState.IDLE
    if coverage.directories == 0:
        return InvestigationProgressState.DISCOVERING
    if coverage.configuration == 0 or (coverage.entrypoints == 0 and coverage.modules == 0):
        return InvestigationProgressState.MAPPING
    if coverage.files < 3:
        return InvestigationProgressState.ANALYZING
    
    sufficient, _ = coverage.is_sufficient_for_investigation()
    if not sufficient:
        return InvestigationProgressState.VERIFYING
    return InvestigationProgressState.REPORTING


def check_investigation_gates(user_prompt: str, records: List[Any], report_text: str = "") -> tuple[bool, str]:
    """Check Phase 3, Phase 8, and Phase 9 completion gates.

    Returns ``(passed, failure_reason_or_details)``.
    If `user_prompt` does not require multi-stage investigation, passes automatically.
    """
    intent = classify_intent(user_prompt)
    if not is_multi_stage_investigation(intent):
        return (True, "Not a multi-stage repository investigation request.")

    coverage = CoverageMetrics.from_records(records)
    current_state = compute_investigation_state(coverage)

    # Phase 9: Anti-Premature Completion Rule
    if coverage.files <= 1 and len(records) <= 2:
        return (
            False,
            f"[ANTI-PREMATURE COMPLETION RULE] You attempted to finish the '{intent}' after only inspecting {coverage.files} file(s) / {len(records)} tool call(s).\n"
            "A single observation or file MUST NEVER satisfy a repository-wide request.\n"
            "You MUST continue exploring the repository systematically across multiple modules before emitting FINAL_ANSWER."
        )

    # Phase 3: Completion Gates check
    sufficient, missing_gates = coverage.is_sufficient_for_investigation()
    if not sufficient or current_state != InvestigationProgressState.REPORTING:
        formatted_missing = "\n".join(f"- ❌ {m}" for m in missing_gates) if missing_gates else "- ❌ State not yet REPORTING."
        plan_formatted = "\n".join(f"  {i+1}. {step}" for i, step in enumerate(MANDATORY_INVESTIGATION_PLAN))
        return (
            False,
            f"[INVESTIGATION COMPLETION GATES FAILED] Request classified as '{intent}'.\n"
            f"Current Investigation State: {current_state.value} (Must transition to REPORTING to finish).\n\n"
            f"Missing Mandatory Evidence Requirements:\n{formatted_missing}\n\n"
            f"Current Coverage Metrics:\n"
            f"  • Directories explored: {coverage.directories}\n"
            f"  • Modules discovered: {coverage.modules}\n"
            f"  • Configuration files: {coverage.configuration}\n"
            f"  • Entry points checked: {coverage.entrypoints}\n"
            f"  • Files inspected: {coverage.files} (Required: >= 3)\n\n"
            f"Mandatory Investigation Plan (Continue execution without skipping):\n{plan_formatted}\n\n"
            "Do NOT emit FINAL_ANSWER or conclude until all mandatory gates are satisfied."
        )

    return (True, f"All mandatory repository investigation gates passed (Coverage: {coverage.files} files across {coverage.modules} modules).")


def build_investigation_protocol_prompt(user_prompt: str) -> str:
    """Build system instructions to inject into context when task is an investigation."""
    intent = classify_intent(user_prompt)
    if not is_multi_stage_investigation(intent):
        return ""

    plan_str = "\n".join(f"{i+1}. {stage}" for i, stage in enumerate(MANDATORY_INVESTIGATION_PLAN))
    return (
        f"## MANDATORY REPOSITORY INVESTIGATION PROTOCOL (`{intent}`)\n"
        "This request requires a goal-driven, multi-stage repository exploration.\n"
        "CRITICAL ARCHITECTURAL RULE: A single observation or file lookup MUST NEVER satisfy a repository-wide request.\n\n"
        "Mandatory Execution Plan (You cannot skip stages and MUST NOT finish early):\n"
        f"{plan_str}\n\n"
        "Investigation Progress States:\n"
        "IDLE -> DISCOVERING -> MAPPING -> ANALYZING -> VERIFYING -> REPORTING\n\n"
        "Your task completion is gated by strict repository coverage checks (directories, build configuration, entrypoints, and inspecting >= 3 representative source files across major modules). Only conclude from the REPORTING state when sufficient evidence exists.\n\n"
        "FINAL REPORT (MANDATORY — how to actually stop):\n"
        "When you reach the REPORTING state with enough evidence, you MUST terminate by emitting a single JSON tool call:\n"
        '{"tool": "final_answer", "args": {"answer": "<your Markdown report here>"}}\n'
        "The report MUST be clean Markdown (headings, bullet lists, code blocks) — NOT a tool call and NOT raw JSON. "
        "Do NOT end by emitting another exploration tool (e.g. file_system list/read). Once you have gathered and verified the evidence, "
        "write the synthesis as the 'answer' and call final_answer. If you emit a tool call instead of final_answer, the run will hit its step ceiling and your work will be discarded.\n\n"
        "HARD STOP RULE (budget is tight — do NOT waste steps):\n"
        "• You have a STRICT step budget. Re-listing the same directory or re-reading the same file is forbidden and wastes steps.\n"
        "• After you have listed the repo ONCE and read <= 5 representative files (README, pyproject.toml, main.py, and 2 module files), you have ENOUGH evidence. Immediately move to REPORTING and call final_answer.\n"
        "• Call final_answer as your NEXT action after evidence is sufficient — do not call any more tools. The report is written IN the final_answer call, not in a separate message.\n\n"
        "DIRECTED EXPLORATION (use file_system — the reliable path):\n"
        "• Call file_system with action='list' path='.' EXACTLY ONCE to discover top-level modules.\n"
        "• Then call file_system action='read' on >= 3 specific source files (e.g. pyproject.toml, main.py, core/evidence.py).\n"
        "• Your final_answer MUST be an ORIGINAL Markdown synthesis (## headings, - bullets, code blocks) interpreting what you READ — "
        "NEVER echo a directory listing or tool output back as the answer.\n"
        "• OPTIONAL: if the `graphify` CLI is installed, `graph_intel` (action='status'/'build'/'query') can supplement discovery — "
        "but do NOT block on it; if it reports 'CLI not found', proceed with file_system reads.\n"
    )
