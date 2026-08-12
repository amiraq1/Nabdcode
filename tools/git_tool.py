"""Git operation tools with Pydantic self-validation and ToolResult return type."""

from __future__ import annotations

import re
import subprocess
import time
import uuid
from typing import Any, Dict, Optional, Type

from tools.base import BaseTool, BaseModel, Field
from tools.models import ToolResult
from core.evidence import EvidenceRecord
from tools.secure_tools import SecureGitInspector  # moved to top (Phase 3 DI)
from core.kernel.subprocess_guard import default_guard


GIT_ARG_VALIDATOR = re.compile(r'^[a-zA-Z0-9_./-]+$')

# Output truncation ceiling — prevents unbounded git output (huge `log`/`diff`
# results) from bloating the LLM context window and the evidence ledger (GIT-P1-6).
MAX_GIT_OUTPUT: int = 12000


def _truncate_git_output(text: str, limit: int = MAX_GIT_OUTPUT) -> str:
    """Clamp a git output string to ``limit`` chars, marking truncation."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated by git_tool]"


# ── Pydantic argument schema ──
# tools.base re-exports a working BaseModel stub when real pydantic-core is
# unavailable (e.g. Termux/Android), so the class can be defined unconditionally.

class GitPushArgs(BaseModel):
    commit_message: str = Field(
        "chore: automated secure commit",
        max_length=200,
        description="Commit message describing the changes being pushed.",
    )
    branch: str = Field(
        "main",
        description="Target remote branch name (e.g. 'main', 'develop').",
    )
    remote: str = Field(
        "origin",
        description="Remote repository name (e.g. 'origin').",
    )


# ── Standalone functions ────────────────────────────────────────────────

def push_and_verify_evidence(
    evidence_log: Any,
    remote: str = "origin",
    branch: str = "main",
) -> Dict[str, EvidenceRecord]:
    """Execute git push and automatically record deterministic git diff verification evidence."""
    # 1. Execute real git push
    push_res = default_guard.run_git(["git", "push", remote, branch], timeout=30)
    push_raw = _truncate_git_output((push_res[1] or "") + (push_res[2] or ""))
    push_rec = EvidenceRecord(
        tool_name="git_push",
        input=f"{remote} {branch}",
        raw_output=push_raw,
        exit_code=push_res[0],
        timestamp=time.time(),
        call_id=str(uuid.uuid4()),
    )
    evidence_log.add(push_rec)

    # 2. Automatically execute git diff HEAD origin/main without manual intervention
    diff_target = f"{remote}/{branch}"
    diff_res = default_guard.run_git(["git", "diff", "HEAD", diff_target], timeout=30)
    diff_raw = _truncate_git_output((diff_res[1] or "") + (diff_res[2] or ""))
    diff_rec = EvidenceRecord(
        tool_name="git_diff",
        input=f"HEAD {diff_target}",
        raw_output=diff_raw,
        exit_code=diff_res[0],
        timestamp=time.time(),
        call_id=str(uuid.uuid4()),
    )
    evidence_log.add(diff_rec)

    return {
        "push_record": push_rec,
        "diff_record": diff_rec,
    }


# ── GitPushTool ─────────────────────────────────────────────────────────

class GitPushTool(BaseTool):
    """Push commits to a remote branch with automatic evidence logging.

    Validates arguments via Pydantic, checks workspace safety via
    ``SecureGitInspector``, executes the push, and records deterministic
    git diff verification evidence.

    Returns a ``ToolResult`` (not a plain dict) for type-safe consumption
    by the engine dispatcher.
    """

    name: str = "git_push"
    description: str = (
        "Push commits to a remote branch and automatically record git diff "
        "verification evidence in evidence_log. "
        "Optional: commit_message (default 'chore: automated secure commit'), "
        "branch (default 'main'), remote (default 'origin')."
    )

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return GitPushArgs

    # ── Unified execution path ────────────────────────────────────────

    def execute_with_args(self, args: Any, evidence_log: Any = None) -> ToolResult:
        """Execute validated git push with *args*."""
        # Support both GitPushArgs (Pydantic) and raw-dict fallback
        if isinstance(args, dict):
            commit_message = args.get("commit_message", "")
            branch = args.get("branch", "main")
            remote = args.get("remote", "origin")
        else:
            commit_message = args.commit_message
            branch = args.branch
            remote = args.remote

        # 1. Secure workspace inspection
        try:
            inspector = SecureGitInspector()
            is_safe, reason = inspector.inspect_workspace()
            if not is_safe:
                return ToolResult(
                    success=False,
                    stderr=f"Git push blocked by SecureGitInspector: {reason}",
                    returncode=1,
                    status="error",
                )
        except Exception as exc:
            return ToolResult(
                success=False,
                stderr=f"Git push blocked: secure workspace inspection encountered an error ({exc}).",
                returncode=1,
                status="error",
            )

        # 2. Validate git arguments format
        if not GIT_ARG_VALIDATOR.match(remote) or not GIT_ARG_VALIDATOR.match(branch):
            return ToolResult(
                success=False,
                stderr=f"Validation failed: Invalid remote '{remote}' or branch '{branch}' format.",
                returncode=1,
                status="error",
            )

        # 3. Execute evidence push
        if evidence_log is None:
            from core.evidence import EvidenceLog
            evidence_log = EvidenceLog()
        recs = push_and_verify_evidence(evidence_log, remote=remote, branch=branch)

        push_ok = recs["push_record"].success
        diff_ok = recs["diff_record"].success and recs["diff_record"].raw_output.strip() == ""

        if push_ok and diff_ok:
            return ToolResult(
                success=True,
                stdout=(
                    f"Successfully committed and pushed to {branch}: "
                    f"'{commit_message}'"
                ),
                metadata={
                    "push_record_id": recs["push_record"].evidence_id,
                    "diff_record_id": recs["diff_record"].evidence_id,
                    "push_output": recs["push_record"].raw_output,
                    "diff_output": recs["diff_record"].raw_output,
                },
                returncode=0,
                status="success",
            )
        return ToolResult(
            success=False,
            stderr=(
                f"Push to {branch} completed but diff verification found changes. "
                f"Push output: {recs['push_record'].raw_output[:300]}"
            ),
            returncode=1,
            status="error",
        )

    # ── Legacy entry point (backward compatible) ──────────────────────

    def execute(self, **kwargs: Any) -> ToolResult:
        """Legacy ``**kwargs`` entry point — delegates to ``execute_with_args``."""
        commit_message = kwargs.get("commit_message", "")
        branch = kwargs.get("branch", "main")
        remote = kwargs.get("remote", "origin")
        evidence_log = kwargs.get("evidence_log")
        return self.execute_with_args(GitPushArgs(
            commit_message=commit_message,
            branch=branch,
            remote=remote,
        ),
        evidence_log=evidence_log,
        )


# ── GitToolArgs ─────────────────────────────────────────────────────────
# GIT-P0-1: `force_execute` is a first-class schema field so the engine's
# post-approval re-dispatch (`engine/_dispatch.py` sets force_execute=True)
# actually reaches `execute()` instead of being silently dropped by Pydantic.

class GitToolArgs(BaseModel):
    command: str = Field(description="The git command to execute (e.g., 'log -n 3', 'status', 'diff')")
    force_execute: bool = Field(
        False,
        description="Execute write commands without the consent gate (internal use only, set by the engine after user approval).",
    )


class GitTool(BaseTool):
    """
    Execute git commands safely, returning a typed ``ToolResult``.

    Read-only commands (log, diff, status, show, branch, tag) execute
    directly. Write commands (add, commit, checkout, restore) require the
    consent gate: without ``force_execute`` they return a ToolResult with
    ``status="consent_required"``. Destructive commands (push, reset, clean,
    revert) are forbidden outright.
    """
    args_schema = GitToolArgs

    ALLOWED = {"log", "diff", "status", "show", "branch", "tag"}
    WRITE_COMMANDS = {"add", "commit", "checkout", "restore"}
    DANGEROUS_COMMANDS = {"push", "reset", "clean", "revert"}
    # Flags that grant file-write side effects to "read-only" commands (GIT-P0-3).
    # ``-o`` is the short form of ``--output=<file>`` in git diff/show.
    BLOCKED_READ_FLAGS = ("--output", "-o")

    def execute(self, command: str = "", force_execute: bool = False) -> ToolResult:
        # Normalize: tolerate an optional leading "git " prefix from the model.
        cmd_str = (command or "").strip()
        if cmd_str.startswith("git "):
            cmd_str = cmd_str[4:].strip()

        # GIT-P0-3: block file-writing flags smuggled into "read-only" commands.
        tokens = cmd_str.split()
        if any(t.startswith("--output=") or t in self.BLOCKED_READ_FLAGS for t in tokens):
            return ToolResult(
                success=False,
                stderr="--output/-o is not allowed in git read mode (it writes files).",
                returncode=-1,
                status="error",
            )

        cmd = tokens[0] if tokens else ""

        if cmd in self.DANGEROUS_COMMANDS:
            return ToolResult(
                success=False,
                stderr=f"Git command '{cmd}' is forbidden",
                returncode=-1,
                status="error",
            )

        if cmd in self.WRITE_COMMANDS:
            if not force_execute:
                return ToolResult(
                    success=False,
                    stderr=f"Git write command '{cmd}' requires consent (force_execute not set).",
                    returncode=-1,
                    status="consent_required",
                    metadata={
                        "command": command,
                        "preview": (
                            "git diff --staged" if cmd == "commit"
                            else "git diff --cached" if cmd == "add"
                            else f"git diff {cmd} --"
                        ),
                    },
                )
            # Otherwise proceed to execute safely
        elif cmd not in self.ALLOWED:
            return ToolResult(
                success=False,
                stderr=f"Git command '{cmd}' not allowed. Allowed: {sorted(self.ALLOWED)}",
                returncode=-1,
                status="error",
            )

        try:
            result = subprocess.run(
                ["git"] + tokens,
                capture_output=True, text=True, timeout=10,
                cwd=".",  # فقط في cwd الحالي
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                stderr="git executable not found.",
                returncode=-1,
                status="error",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                stderr="git command timed out after 10s.",
                returncode=-1,
                status="error",
            )

        out = _truncate_git_output(result.stdout or result.stderr)
        if result.returncode != 0:
            return ToolResult(
                success=False,
                stdout=out,
                returncode=result.returncode,
                status="error",
            )
        return ToolResult(
            success=True,
            stdout=out,
            returncode=0,
            status="success",
        )
