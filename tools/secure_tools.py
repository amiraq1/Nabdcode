"""Production-grade secure toolchain for Nabd Agent OS.

Implements zero-trust sandboxed file reading, git inspection, and test execution
with strict pathlib boundaries, immutable command allowlists, centralized
sanitization, and safe error handling.

All Secure* tools now extend ``BaseTool`` (not ``smolagents.Tool``), gaining
Pydantic self-validation and UI bridge event emission through the unified
``__call__`` entry point.  The ``forward()`` contract is preserved for
smolagents ``CodeAgent`` compatibility.
"""

from __future__ import annotations

import logging
import os
import pathlib
import time
from typing import Any, Dict, Final, List, Optional, Type

from tools.base import BaseTool
from tools.models import ToolResult
from core.kernel.subprocess_guard import default_guard

# ── Pydantic schema support ──────────────────────────────────────────────
try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:
    BaseModel = None  # type: ignore[assignment]
    Field = None
    ValidationError = None


# ── Lazy sanitizer ────────────────────────────────────────────────────────
# Imported lazily inside each method that needs it so the tools/ package
# never forces the core/ module graph to load at import time.


def _sanitize(text: str, **kwargs) -> str:
    from core.sanitize import sanitize as _do_sanitize
    return _do_sanitize(text, **kwargs)


# Setup logger for SecureTools
logger = logging.getLogger("SecureTools")


class SecureTool(BaseTool):
    """Base class for secure tools with UIBridge event emission + forward contract.

    **Key differences from BaseTool:**

    * ``__call__`` wraps ``forward()`` with UI bridge start/end events (no
      validation — backward compatible with existing smolagents callers).
    * ``forward()`` is the primary execution contract (smolagens convention).
      Subclasses override it instead of ``execute()``.
    * ``inputs`` and ``output_type`` are preserved for smolagents ``CodeAgent``
      schema generation.

    Migration note (Phase 2+):
        New tools should override ``execute(**kwargs)`` or
        ``execute_with_args(args: BaseModel)`` and use ``args_schema`` for
        self-validation.  The ``forward`` shim in ``BaseTool`` will then be
        sufficient for smolagens compatibility.
    """

    # smolagents schema attributes (read by CodeAgent._build_tool_schemas)
    inputs: dict = {}
    output_type: str = "string"

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Wrap forward() with UI bridge start/end events.

        Legacy behaviour preserved exactly: no validation, no Pydantic.
        Validation will be integrated in Phase 2 via the shared
        ``BaseTool.validate_and_parse()``.
        """
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

    def execute(self, **kwargs: Any) -> ToolResult:
        """Redirect ``execute`` to ``forward`` for smolagens-compatible tools.

        This is a backward-compatibility shim so the ``Dispatcher`` (which
        calls ``tool.execute(**kwargs)``) still works.  Tools that override
        ``forward()`` will have their string result wrapped into a ``ToolResult``.
        """
        result_str = self.forward(**kwargs)
        return ToolResult(
            success=not str(result_str).startswith(("Error:", "Security Violation:")),
            stdout=str(result_str),
            returncode=0,
            status="success",
        )


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
        resolved_path = file_path or path or filename or directory or target_dir
        if not resolved_path and kwargs:
            for k, v in kwargs.items():
                if isinstance(v, str) and v.strip():
                    resolved_path = v
                    break
        if not resolved_path:
            return "Error: No file_path or path provided to secure_workspace_reader."
        file_path = str(resolved_path)
        try:
            # Find the first allowed root that can resolve this path
            target_path = None
            matched_root = None
            for root in self.allowed_roots:
                candidate = (root / file_path).resolve()
                if _is_path_relative_to(candidate, root):
                    target_path = candidate
                    matched_root = root
                    break

            if target_path is None:
                logger.warning(
                    f"[{self.name}] Validation failed: Path '{file_path}' not under any allowed root"
                )
                return (
                    "Security Violation: Access denied outside allowed workspace roots. "
                    f"Allowed roots: {[str(r) for r in self.allowed_roots]}"
                )

            # 2. Verify file exists
            if not target_path.exists():
                logger.info(f"[{self.name}] File not found: {file_path}")
                return f"Error: File '{file_path}' not found."

            # 3. Reject directories
            if target_path.is_dir():
                logger.warning(
                    f"[{self.name}] Validation failed: Attempted directory read on {file_path}"
                )
                return f"Error: Target '{file_path}' is a directory, not a file."

            # 4. Reject oversized files
            file_size = target_path.stat().st_size
            if file_size > self.max_file_size:
                logger.warning(
                    f"[{self.name}] Validation failed: Oversized file ({file_size} bytes)"
                )
                return f"Error: File '{file_path}' exceeds maximum allowed size ({self.max_file_size} bytes)."

            # 5. Detect binary files
            with target_path.open("rb") as f:
                header = f.read(1024)
                if b"\x00" in header:
                    logger.warning(
                        f"[{self.name}] Validation failed: Binary file detected ({file_path})"
                    )
                    return f"Error: Cannot read binary file '{file_path}'."

            # 6. Read text and handle encoding failures gracefully
            try:
                content = target_path.read_text(encoding="utf-8")

                # Token-clamp oversized files to protect local-model context.
                MAX_CONTENT_CHARS = 12000
                if len(content) > MAX_CONTENT_CHARS:
                    logger.warning(f"[{self.name}] Truncating output ({len(content)} chars)")
                    content = content[:MAX_CONTENT_CHARS] + (
                        f"\n\n... [TRUNCATED] Content exceeded {MAX_CONTENT_CHARS} chars. "
                        "Use shell tools (grep/head) for targeted inspection."
                    )

            except UnicodeDecodeError:
                logger.warning(
                    f"[{self.name}] Validation failed: Non-UTF8 encoding in {file_path}"
                )
                return f"Error: File '{file_path}' is not valid UTF-8 text."

            # 7. Pass output through centralized sanitizer
            duration = time.time() - start_time
            logger.info(
                f"[{self.name}] Read successful ({len(content)} chars, {duration:.3f}s)"
            )
            return _sanitize(content)

        except (PermissionError, OSError) as exc:
            duration = time.time() - start_time
            logger.error(f"[{self.name}] OSError during read ({duration:.3f}s)")
            return f"Error: Operating system error accessing file ({type(exc).__name__})."


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
            returncode, stdout, stderr = default_guard.run_infra(
                cmd,
                cwd=str(self.repo_path),
                timeout=self.timeout,
            )
            duration = time.time() - start_time
            logger.info(
                f"[{self.name}] Execution finished (exit code {returncode}, {duration:.3f}s)"
            )

            out_sanitized = _sanitize(stdout)
            err_sanitized = _sanitize(stderr)

            if returncode != 0:
                return f"Error executing git {action}: {err_sanitized or 'Unknown error'}"

            return out_sanitized if out_sanitized.strip() else f"Git {action} returned empty output."

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
            returncode, stdout, stderr = default_guard.run_infra(
                cmd,
                cwd=str(self.repo_path),
                timeout=self.timeout,
            )
            duration = time.time() - start_time
            logger.info(
                f"[{self.name}] Execution finished (exit code {returncode}, {duration:.3f}s)"
            )

            out_sanitized = _sanitize(stdout)
            err_sanitized = _sanitize(stderr)

            combined = f"{out_sanitized}\n{err_sanitized}".strip()
            return combined if combined else "Tests executed, but no output was returned."

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
        from core.storage import SemanticMemoryPipeline
        self.memory = memory_pipeline or SemanticMemoryPipeline()

    def forward(self, action: str, text: str) -> str:
        clean_action = _sanitize(action).strip().lower()
        clean_text = _sanitize(text).strip()

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


# ── Pydantic schema for file system operations ───────────────────────────

if BaseModel is not None:

    class SecureFileSystemArgs(BaseModel):
        """Validated arguments for ``SecureFileSystemTool``."""

        action: str = Field(
            ...,
            pattern=r"^(read|write|append|replace)$",
            description="File operation: read, write, append, or replace.",
        )
        path: str = Field(
            ...,
            min_length=1,
            max_length=4096,
            description="Relative or absolute path within the workspace jail.",
        )
        content: Optional[str] = Field(
            default=None,
            description="Content for write/append actions.",
        )
        old_text: Optional[str] = Field(
            default=None,
            description="Text to replace (for replace action).",
        )
        new_text: Optional[str] = Field(
            default=None,
            description="Replacement text (for replace action).",
        )

    SecureFileSystemArgs.model_rebuild()


class SecureFileSystemTool(SecureTool):
    """smolagents-compatible wrapper around the hardened FileSystemTool.

    Features:
    * Self-validating args via Pydantic ``SecureFileSystemArgs`` schema.
    * Delegates to ``FileSystemTool.execute`` (workspace jail + token clamp).
    * Emits unified diff through the UI bridge on mutations.
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

    @property
    def args_schema(self) -> Type["BaseModel"] | None:
        """Pydantic schema for self-validation."""
        if BaseModel is None:
            return None
        return SecureFileSystemArgs

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

        # ── Self-validation (if Pydantic is available) ───────────────
        # Validate the incoming raw args against the Pydantic schema.
        # On failure we return the LLM-readable error without crashing.
        if BaseModel is not None:
            try:
                validated = self.validate_and_parse({
                    "action": action,
                    "path": resolved_path,
                    "content": content,
                    "old_text": old_text,
                    "new_text": new_text,
                })
                # Use validated values (Pydantic normalises casing, strips
                # whitespace, and enforces types).
                action = validated.action
                resolved_path = validated.path
                content = validated.content
                old_text = validated.old_text
                new_text = validated.new_text
            except ValueError as exc:
                return str(exc)

        result = self._tool.execute(
            action=action,
            path=resolved_path,
            content=content,
            old_text=old_text,
            new_text=new_text,
        )

        # ── File-Modification Emitter (Dependency Inversion) ──────────
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

    Accepts optional Dependency Injection for the underlying ShellTool's
    security engine, sanitizer, and command executor. When omitted, default
    implementations from core/ are lazily loaded (backward compatible).
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

    def __init__(
        self,
        *args: Any,
        security_engine: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        from tools.shell import ShellTool
        if security_engine is not None:
            self._tool = ShellTool(security_engine=security_engine)
        else:
            self._tool = ShellTool()

    def forward(self, *args: Any, command: Any = "", **kwargs: Any) -> str:
        # Tolerate model schema drift & positional/list unpacking:
        cmd = None
        if args:
            first_arg = args[0]
            if isinstance(first_arg, (list, tuple)) and first_arg:
                cmd = first_arg[0]
            elif isinstance(first_arg, dict):
                cmd = first_arg.get("command") or first_arg.get("cmd") or first_arg.get("file_path") or first_arg.get("path")
            else:
                cmd = first_arg

        if not cmd and command:
            if isinstance(command, (list, tuple)) and command:
                cmd = command[0]
            elif isinstance(command, dict):
                cmd = command.get("command") or command.get("cmd") or command.get("file_path") or command.get("path")
            else:
                cmd = command

        if not cmd:
            raw = kwargs.get("command") or kwargs.get("cmd") or kwargs.get("file_path") or kwargs.get("path") or kwargs.get("args")
            if isinstance(raw, (list, tuple)) and raw:
                cmd = raw[0]
            elif isinstance(raw, dict):
                cmd = raw.get("command") or raw.get("cmd") or raw.get("file_path") or raw.get("path")
            else:
                cmd = raw

        if not cmd and kwargs:
            for k, v in kwargs.items():
                if isinstance(v, (list, tuple)) and v and isinstance(v[0], str):
                    cmd = v[0]
                    break
                elif isinstance(v, str) and v.strip():
                    cmd = v
                    break

        if not cmd:
            return "Error: secure_shell requires a 'command' argument."
        result = self._tool.execute(command=str(cmd))
        if not result.success:
            detail = result.stderr or result.stdout or "unknown error"
            return f"Error executing '{str(cmd)}' (exit {result.returncode}): {detail}"
        out = result.stdout or result.stderr
        return str(out).strip()


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
        result = self._tool.execute(query=_sanitize(str(q)[:500]))
        return result.output if hasattr(result, "output") else str(result)


class SecureBrowserTool(SecureTool):
    """Securely interacts with Lightpanda MCP adapter to navigate webpages and extract text."""

    name = "browser_action"
    description = (
        "تصفح الويب، استخراج النصوص المنسقة، والتعامل مع صفحات الإنترنت بصمت وخفة "
        "عبر مهايئ Lightpanda MCP. استخدم هذه الأداة حصراً عندما يطلب المستخدم معلومات حديثة من الإنترنت، "
        "أو قراءة توثيق (Documentation) لرابط معين، أو البحث أونلاين."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "اسم الأداة الفرعية لـ MCP. الخيارات المتاحة: 'navigate' لزيارة الرابط، أو 'get_text' لاستخراج النصوص النظيفة.",
            "required": True,
        },
        "url": {
            "type": "string",
            "description": "الرابط الكامل للموقع المراد زيارته (مطلوب فقط عند استخدام action: 'navigate').",
            "required": False,
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, workspace_dir: str = ".", *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from tools.browser_tool import BrowserTool
        self._tool = BrowserTool(workspace_dir=workspace_dir)

    def forward(self, action: str = "", url: str = "", **kwargs: Any) -> str:
        act = action or kwargs.get("action", "")
        if not act:
            return "Error: browser_action requires an 'action' argument ('navigate' or 'get_text')."
        exec_kwargs = {}
        if url or kwargs.get("url"):
            exec_kwargs["url"] = url or kwargs.get("url")
        exec_kwargs.update({k: v for k, v in kwargs.items() if k not in ("action", "url")})
        result = self._tool.execute(action=str(act), **exec_kwargs)
        if not result.success:
            return f"Error ({result.returncode}): {result.stderr or result.stdout}"
        return str(result.stdout or result.stderr).strip()


class SecureCodeIntelligenceTool(SecureTool):
    """smolagents-compatible wrapper around CodeIntelligenceTool."""

    name = "secure_code_intelligence"
    description = (
        "AST structural code intelligence for Python files. "
        "Actions: 'list_symbols' (returns classes, methods, and functions with line numbers/docstrings) or "
        "'get_definition' (finds exact file path, line range, and docstring where a symbol is defined). "
        "Required args: action, path. Optional: symbol."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "One of: list_symbols, get_definition.",
        },
        "path": {
            "type": "string",
            "description": "Target file path or directory within workspace (use '.' for workspace root).",
        },
        "symbol": {
            "type": "string",
            "description": "Symbol name (required for get_definition).",
            "required": False,
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, workspace: str | Path = ".", *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from tools.code_intelligence import CodeIntelligenceTool
        self._tool = CodeIntelligenceTool(workspace=workspace)

    def forward(self, action: str = "", path: str = ".", symbol: str = "", **kwargs: Any) -> str:
        act = action or kwargs.get("action", "")
        if not act:
            return "Error: code_intelligence requires an 'action' argument ('list_symbols' or 'get_definition')."
        result = self._tool.execute(action=str(act), path=str(path or kwargs.get("path", ".")), symbol=str(symbol or kwargs.get("symbol", "")), **kwargs)
        if not result.success:
            return f"Error ({result.returncode}): {result.stderr or result.stdout}"
        return str(result.stdout or result.stderr).strip()


class SecurePythonREPLTool(SecureTool):
    """smolagents-compatible wrapper around PythonREPLTool."""

    name = "secure_python_repl"
    description = (
        "A Python execution shell inside a secure sandbox directory (.nabd/sandbox). "
        "Includes AST safety verification and a 15-second circuit breaker for infinite loops. "
        "Required arg: 'code' (str). Use print() to output results."
    )
    inputs = {
        "code": {
            "type": "string",
            "description": "The valid Python script to execute. Use print() to output results.",
        },
    }
    output_type = "string"

    def __init__(self, workspace: str | Path = ".", *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from tools.python_repl import PythonREPLTool
        self._tool = PythonREPLTool(workspace=workspace)

    def forward(self, code: str = "", **kwargs: Any) -> str:
        code_str = code or kwargs.get("code", "")
        if not code_str:
            return "Error: python_repl requires a 'code' argument."
        result = self._tool.execute(code=str(code_str))
        if not result.success:
            return f"Error ({result.returncode}): {result.stderr or result.stdout}"
        return str(result.stdout or result.stderr).strip()


class SecureTasteManagerTool(SecureTool):
    """smolagents-compatible wrapper around TasteManagerTool."""

    name = "secure_taste_manager"
    description = (
        "Manage and update the developer's Neuro-Symbolic Taste Profile (.nabd/taste_profile.json). "
        "Use this tool when the user explicitly corrects your coding style, architecture, "
        "or asks you to 'remember' a specific preference for all future interactions."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "The action to perform: 'view' (to see current taste), 'add_rule', or 'remove_rule'.",
        },
        "category": {
            "type": "string",
            "description": "The category to modify: 'architectural_rules', 'code_styling', 'language_preferences', or 'custom_rules'. Optional for 'view'.",
            "nullable": True,
        },
        "rule": {
            "type": "string",
            "description": "The exact text of the rule to add or remove. Optional for 'view'.",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, taste_engine: Optional[Any] = None, workspace: str | Path = ".", *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from tools.taste_manager import TasteManagerTool
        self._tool = TasteManagerTool(taste_engine=taste_engine, workspace=workspace)

    def forward(self, action: str = "", category: Optional[str] = None, rule: Optional[str] = None, **kwargs: Any) -> str:
        act = action or kwargs.get("action", "")
        if not act:
            return "Error: taste_manager requires an 'action' argument ('view', 'add_rule', or 'remove_rule')."
        return self._tool.forward(
            action=str(act),
            category=category or kwargs.get("category"),
            rule=rule or kwargs.get("rule"),
        )


class SecureGraphifyTool(SecureTool):
    """smolagents-compatible wrapper around GraphifyTool."""

    name = "secure_graphify_tool"
    description = (
        "Consult the graphify knowledge graph for codebase and architecture questions. "
        "Use 'query <question>' for general structure, 'path <A> <B>' for relationships between components, "
        "'explain <concept>' for focused details, and 'update' after modifying code files."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "The graphify action to perform: 'query', 'path', 'explain', or 'update'.",
        },
        "target": {
            "type": "string",
            "description": "The search query, concept to explain, or the source node for 'path' action. Optional for 'update'.",
            "nullable": True,
        },
        "target_b": {
            "type": "string",
            "description": "The destination node. ONLY used when action is 'path'.",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path = ".", workspace: str | Path | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from tools.graphify_tool import GraphifyTool
        path_arg = workspace or workspace_dir or kwargs.get("workspace") or kwargs.get("workspace_dir") or "."
        self._tool = GraphifyTool(workspace_dir=path_arg)

    def forward(self, action: str = "", target: Optional[str] = None, target_b: Optional[str] = None, **kwargs: Any) -> str:
        act = action or kwargs.get("action", "")
        if not act:
            return "Error: graphify_tool requires an 'action' argument ('query', 'path', 'explain', or 'update')."
        return self._tool.forward(
            action=str(act),
            target=target or kwargs.get("target"),
            target_b=target_b or kwargs.get("target_b"),
        )


