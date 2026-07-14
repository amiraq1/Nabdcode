"""Production-grade secure toolchain for Nabd Agent OS.

Implements zero-trust sandboxed file reading, git inspection, and test execution
with strict pathlib boundaries, immutable command allowlists, centralized
sanitization, and safe error handling.
"""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
import time
from typing import Any, Dict, Final, List, Optional
from smolagents import Tool
from core.sanitize import sanitize

# Setup logger for SecureTools
logger = logging.getLogger("SecureTools")


class SecureTool(Tool):
    """Base class for secure tools that automatically emits UIBridge start/end events."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        from core.ui_bridge import get_bridge
        bridge = get_bridge()
        call_args = kwargs if kwargs else {f"arg_{i}": str(a) for i, a in enumerate(args)}
        bridge.emit_tool_start_sync(getattr(self, "name", self.__class__.__name__), call_args)
        try:
            res = self.forward(*args, **kwargs)
            summary = str(res)[:150]
            bridge.emit_tool_end_sync(getattr(self, "name", self.__class__.__name__), summary)
            return res
        except Exception as e:
            bridge.emit_tool_end_sync(getattr(self, "name", self.__class__.__name__), f"❌ Error: {str(e)[:120]}")
            raise


def _is_path_relative_to(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Check if path is relative to root safely across Python versions."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


class SecureWorkspaceReader(SecureTool):
    """Securely reads files within a pinned workspace root with full validation."""

    name = "secure_workspace_reader"
    description = "Reads a file securely from within the pinned workspace root only. Allowed roots: smart-agent and 9router directories."
    inputs = {
        "file_path": {
            "type": "string",
            "description": "The relative or absolute path of the file to read (e.g. 'smolagents/__init__.py' or '/home/user/9router/llm_router.py').",
            "nullable": True,
        },
        "path": {
            "type": "string",
            "description": "Alternative parameter name for file_path.",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(
        self,
        workspace_root: str | None = None,
        allowed_roots: list[str] | None = None,
        max_file_size: int = 10 * 1024 * 1024,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # Support single workspace_root (legacy) or multi-root list
        if allowed_roots:
            self.allowed_roots = [pathlib.Path(r).resolve() for r in allowed_roots]
        elif workspace_root:
            self.allowed_roots = [pathlib.Path(workspace_root).resolve()]
        else:
            self.allowed_roots = [pathlib.Path.cwd().resolve()]
        self.max_file_size = max_file_size
        logger.info(
            f"[{self.name}] Multi-Root mounts active: {[str(r) for r in self.allowed_roots]}"
        )

    def forward(
        self,
        file_path: str | None = None,
        path: str | None = None,
        filename: str | None = None,
        directory: str | None = None,
        target_dir: str | None = None,
        **kwargs: Any,
    ) -> str:
        start_time = time.time()
        resolved_path = self._resolve_input_path(file_path, path, filename, directory, target_dir, kwargs)
        if not resolved_path:
            return "Error: No file_path or path provided to secure_workspace_reader."
        file_path_str = str(resolved_path)

        try:
            target_path = self._find_target_under_roots(file_path_str)
            if target_path is None:
                logger.warning(
                    f"[{self.name}] Validation failed: Path '{file_path_str}' not under any allowed root"
                )
                return (
                    "Security Violation: Access denied outside allowed workspace roots. "
                    f"Allowed roots: {[str(r) for r in self.allowed_roots]}"
                )

            err_msg, content = self._validate_and_read_file(target_path, file_path_str)
            if err_msg is not None:
                return err_msg

            duration = time.time() - start_time
            logger.info(
                f"[{self.name}] Read successful ({len(content)} chars, {duration:.3f}s)"
            )
            return sanitize(content)

        except (PermissionError, OSError) as exc:
            duration = time.time() - start_time
            logger.error(f"[{self.name}] OSError during read ({duration:.3f}s)")
            return f"Error: Operating system error accessing file ({type(exc).__name__})."

    def _resolve_input_path(self, file_path, path, filename, directory, target_dir, kwargs) -> Optional[str]:
        """Resolve path from positional keyword arguments or fallback kwargs."""
        resolved = file_path or path or filename or directory or target_dir
        if not resolved and kwargs:
            for k, v in kwargs.items():
                if isinstance(v, str) and v.strip():
                    return v
        return resolved

    def _find_target_under_roots(self, file_path: str) -> Optional[pathlib.Path]:
        """Find the first allowed root that can safely resolve candidate file path."""
        for root in self.allowed_roots:
            candidate = (root / file_path).resolve()
            if _is_path_relative_to(candidate, root):
                return candidate
        return None

    def _validate_and_read_file(self, target_path: pathlib.Path, file_path: str) -> tuple[Optional[str], str]:
        """Validate existence, type, size, encoding of target file and return (error_string, content)."""
        if not target_path.exists():
            logger.info(f"[{self.name}] File not found: {file_path}")
            return f"Error: File '{file_path}' not found.", ""

        if target_path.is_dir():
            logger.warning(f"[{self.name}] Validation failed: Attempted directory read on {file_path}")
            return f"Error: Target '{file_path}' is a directory, not a file.", ""

        file_size = target_path.stat().st_size
        if file_size > self.max_file_size:
            logger.warning(f"[{self.name}] Validation failed: Oversized file ({file_size} bytes)")
            return f"Error: File '{file_path}' exceeds maximum allowed size ({self.max_file_size} bytes).", ""

        with target_path.open("rb") as f:
            header = f.read(1024)
            if b"\x00" in header:
                logger.warning(f"[{self.name}] Validation failed: Binary file detected ({file_path})")
                return f"Error: Cannot read binary file '{file_path}'.", ""

        try:
            content = target_path.read_text(encoding="utf-8")
            MAX_CONTENT_CHARS = 12000
            if len(content) > MAX_CONTENT_CHARS:
                logger.warning(f"[{self.name}] Truncating output ({len(content)} chars)")
                content = content[:MAX_CONTENT_CHARS] + (
                    f"\n\n... [TRUNCATED] Content exceeded {MAX_CONTENT_CHARS} chars. "
                    "Use shell tools (grep/head) for targeted inspection."
                )
            return None, content
        except UnicodeDecodeError:
            logger.warning(f"[{self.name}] Validation failed: Non-UTF8 encoding in {file_path}")
            return f"Error: File '{file_path}' is not valid UTF-8 text.", ""


ALLOWED_GIT_COMMANDS: Final[Dict[str, List[str]]] = {
    "status": ["git", "status", "--short"],
    "diff": ["git", "diff"],
}


class SecureGitInspector(SecureTool):
    """Inspects Git status or diff securely using immutable allowlists."""

    name = "secure_git_inspector"
    description = (
        "Inspects the local git repository status or diff securely without flag injection."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "The git action to perform. Allowed values: 'status' or 'diff'.",
        }
    }
    output_type = "string"

    def __init__(
        self,
        repo_path: str = ".",
        timeout: int = 10,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.repo_path = pathlib.Path(repo_path).resolve()
        self.timeout = timeout

    def forward(self, action: str) -> str:
        start_time = time.time()
        # 1. Validate action against immutable allowlist
        if action not in ALLOWED_GIT_COMMANDS:
            logger.warning(
                f"[{self.name}] Validation failed: Unauthorized action '{action}'"
            )
            return "Security Violation: Invalid action. Only 'status' and 'diff' are allowed."

        # 2. Verify working directory is a Git repository
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            duration = time.time() - start_time
            logger.warning(
                f"[{self.name}] Validation failed: Not a git repository ({duration:.3f}s)"
            )
            return "Error: Working directory is not a Git repository."

        cmd = ALLOWED_GIT_COMMANDS[action]

        try:
            result = subprocess.run(  # nosec - verified safe
                cmd,
                cwd=str(self.repo_path),
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            duration = time.time() - start_time
            logger.info(
                f"[{self.name}] Execution finished (exit code {result.returncode}, {duration:.3f}s)"
            )

            out_sanitized = sanitize(result.stdout)
            err_sanitized = sanitize(result.stderr)

            if result.returncode != 0:
                return f"Error executing git {action}: {err_sanitized or 'Unknown error'}"

            return out_sanitized if out_sanitized.strip() else f"Git {action} returned empty output."

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            logger.warning(f"[{self.name}] Execution timed out ({duration:.3f}s)")
            return f"Error: Git {action} timed out."
        except FileNotFoundError:
            return "Error: git executable not found."
        except (PermissionError, OSError) as exc:
            return f"Error: Operating system error during execution ({type(exc).__name__})."


ALLOWED_TEST_TARGETS: Final[Dict[str, str]] = {
    "unit": "tests/unit",
    "integration": "tests/integration",
    "all": "tests",
    "tests": "tests",
}


class SecureTestRunner(SecureTool):
    """Runs Python unit tests securely using immutable target allowlist."""

    name = "secure_test_runner"
    description = "Runs python unit tests securely within the repository to generate verification evidence."
    inputs = {
        "test_target": {
            "type": "string",
            "description": "The specific test target to run ('unit', 'integration', 'all', or 'tests').",
        }
    }
    output_type = "string"

    def __init__(
        self,
        repo_path: str = ".",
        timeout: int = 30,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.repo_path = pathlib.Path(repo_path).resolve()
        self.timeout = timeout

    def forward(self, test_target: str) -> str:
        start_time = time.time()

        # 1. Validate against immutable target allowlist
        cleaned_target = test_target.strip()
        if cleaned_target not in ALLOWED_TEST_TARGETS:
            logger.warning(
                f"[{self.name}] Validation failed: Unknown target '{test_target}'"
            )
            return (
                f"Security Violation: Target '{test_target}' is not allowed. "
                f"Allowed targets: {sorted(ALLOWED_TEST_TARGETS.keys())}."
            )

        target_path = ALLOWED_TEST_TARGETS[cleaned_target]
        cmd = ["python3", "-m", "unittest", "discover", "-s", target_path, "--"]

        try:
            result = subprocess.run(  # nosec - verified safe
                cmd,
                cwd=str(self.repo_path),
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            duration = time.time() - start_time
            logger.info(
                f"[{self.name}] Execution finished (exit code {result.returncode}, {duration:.3f}s)"
            )

            out_sanitized = sanitize(result.stdout)
            err_sanitized = sanitize(result.stderr)

            combined = f"{out_sanitized}\n{err_sanitized}".strip()
            return combined if combined else "Tests executed, but no output was returned."

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            logger.warning(f"[{self.name}] Execution timed out ({duration:.3f}s)")
            return "Error: Test runner timed out (Possible infinite loop detected in tests)."
        except FileNotFoundError:
            return "Error: python3 executable not found."
        except (PermissionError, OSError) as exc:
            return f"Error: Operating system error during execution ({type(exc).__name__})."


class SecureSemanticMemoryTool(SecureTool):
    """Searches or stores past experiences and lessons in the zero-trust semantic memory pipeline."""

    name = "secure_semantic_memory"
    description = (
        "Searches past lessons/context or stores new lessons in the zero-trust semantic memory."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "Allowed values: 'search' to look up lessons, or 'store' to save a lesson.",
        },
        "text": {
            "type": "string",
            "description": "The search query or the lesson content to store.",
        },
    }
    output_type = "string"

    def __init__(
        self,
        memory_pipeline: Optional[Any] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        from core.memory import SemanticMemoryPipeline
        self.memory = memory_pipeline or SemanticMemoryPipeline()

    def forward(self, action: str, text: str) -> str:
        clean_action = sanitize(action).strip().lower()
        clean_text = sanitize(text).strip()

        if clean_action not in ["search", "store"]:
            return "Security Violation: Invalid action. Only 'search' or 'store' are allowed."

        if not clean_text:
            return "Error: text parameter cannot be empty."

        if clean_action == "store":
            mem_id = self.memory.add_memory(content=clean_text, role="agent")
            return f"Successfully stored lesson in semantic memory (id={mem_id})."

        # Search action
        results = self.memory.search_memory(clean_text, top_k=3)
        if not results:
            return "No relevant past lessons found in semantic memory."

        formatted = "\n".join(
            f"- [Score: {r.get('similarity_score', 0)}] {r['content']}" for r in results
        )
        return f"Retrieved Semantic Memory Lessons:\n{formatted}"


class SecureFileSystemTool(SecureTool):
    """smolagents-compatible wrapper around the hardened tools.file_system.FileSystemTool.

    Delegates to FileSystemTool.execute (which enforces the workspace jail and
    the token clamp added in the memory-guard hardening pass), exposing it via
    the smolagents ``forward`` contract expected by CodeAgent.
    """

    name = "secure_file_system"
    description = (
        "Read, write, append, or replace text in files inside the workspace. "
        "Required args: 'action' ('read','write','append','replace'), 'path' (str). "
        "For write/append pass 'content' (str); for replace pass 'old_text','new_text'."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "One of: read, write, append, replace.",
        },
        "path": {
            "type": "string",
            "description": "Relative or absolute path of the file within the workspace jail.",
        },
        "content": {
            "type": "string",
            "description": "Content for write/append actions.",
        },
        "old_text": {
            "type": "string",
            "description": "Text to replace (for replace action).",
        },
        "new_text": {
            "type": "string",
            "description": "Replacement text (for replace action).",
        },
    }
    output_type = "string"

    def __init__(
        self,
        workspace: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        from tools.file_system import FileSystemTool
        self._tool = FileSystemTool(workspace=workspace or ".")

    def forward(
        self,
        action: str,
        path: str | None = None,
        content: str | None = None,
        old_text: str | None = None,
        new_text: str | None = None,
        **kwargs: Any,
    ) -> str:
        # Tolerate model schema drift: map 'file_path' synonym to 'path'.
        resolved_path = path or kwargs.get("file_path")
        if not resolved_path:
            return "Error: secure_file_system requires a 'path' argument."
        result = self._tool.execute(
            action=action,
            path=resolved_path,
            content=content,
            old_text=old_text,
            new_text=new_text,
        )

        # ── File-Modification Emitter (Dependency Inversion) ──────────
        # Push the computed unified diff to the abstract UI bridge so the
        # DiffBlock lights up in real time. We only broadcast mutating
        # actions (write/append/replace) — never 'read', to keep the UI
        # clean. The bridge is a no-op unless a concrete controller is
        # injected via core.ui_bridge.set_bridge(). Guarded so a bridge
        # failure can never break the agent loop or the file operation.
        if action in ("write", "append", "replace"):
            diff = result.get("diff") or ""
            if diff:
                try:
                    from core.ui_bridge import get_bridge
                    get_bridge().on_file_modified(diff)
                except Exception as _emit_exc:
                    logger.warning(f"UI bridge (file_modified) emit failed: {_emit_exc}")

        return str(result.get("output") or result.get("stdout") or result.get("stderr") or "")


class SecureShellTool(SecureTool):
    """smolagents-compatible wrapper around the hardened tools.shell.ShellTool.

    Delegates to ShellTool.execute (security validation + safe_execute_command +
    stdout/stderr token clamp), exposed via the smolagents ``forward`` contract.
    """

    name = "secure_shell"
    description = (
        "Execute safe non-interactive Linux/Termux shell commands. "
        "Pass 'command' (str). Never run interactive REPLs. "
        "Binary/flag allowlist is enforced by the security layer."
    )
    inputs = {
        "command": {
            "type": "string",
            "description": "The shell command to execute (validated against the binary/flag allowlist).",
        },
    }
    output_type = "string"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from tools.shell import ShellTool
        self._tool = ShellTool()

    def forward(self, *args: Any, command: Any = "", **kwargs: Any) -> str:
        cmd = self._extract_cmd(args, command, kwargs)
        if not cmd:
            return "Error: secure_shell requires a 'command' argument."
        result = self._tool.execute(command=str(cmd))
        if not result.success:
            detail = result.stderr or result.stdout or "unknown error"
            return f"Error executing '{str(cmd)}' (exit {result.returncode}): {detail}"
        out = result.stdout or result.stderr
        return str(out).strip()

    def _extract_cmd(self, args: tuple[Any, ...], command: Any, kwargs: dict[str, Any]) -> Optional[Any]:
        """Extract command argument from positional args, keyword argument, or kwargs mappings."""
        if args:
            first_arg = args[0]
            if isinstance(first_arg, (list, tuple)) and first_arg:
                return first_arg[0]
            if isinstance(first_arg, dict):
                return first_arg.get("command") or first_arg.get("cmd") or first_arg.get("file_path") or first_arg.get("path")
            return first_arg

        if command:
            if isinstance(command, (list, tuple)) and command:
                return command[0]
            if isinstance(command, dict):
                return command.get("command") or command.get("cmd") or command.get("file_path") or command.get("path")
            return command

        raw = kwargs.get("command") or kwargs.get("cmd") or kwargs.get("file_path") or kwargs.get("path") or kwargs.get("args")
        if raw:
            if isinstance(raw, (list, tuple)) and raw:
                return raw[0]
            if isinstance(raw, dict):
                return raw.get("command") or raw.get("cmd") or raw.get("file_path") or raw.get("path")
            return raw

        for k, v in kwargs.items():
            if isinstance(v, (list, tuple)) and v and isinstance(v[0], str):
                return v[0]
            if isinstance(v, str) and v.strip():
                return v
        return None


class SecureWebSearchTool(SecureTool):
    """Securely searches the web via DuckDuckGo with sanitization and timeout guard."""

    name = "web_search"
    description = "Searches the web for technical documentation, libraries, or error solutions."
    inputs = {
        "query": {
            "type": "string",
            "description": "The search query string.",
        },
    }
    output_type = "string"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from tools.web_search import WebSearchTool
        self._tool = WebSearchTool()

    def forward(self, query: str = "", **kwargs: Any) -> str:
        q = query or kwargs.get("query") or kwargs.get("q")
        if not q:
            return "Error: web_search requires a 'query' argument."
        result = self._tool.execute(query=sanitize(str(q)[:500]))
        return result.output if hasattr(result, "output") else str(result)


