from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Any, Optional

from tools.base import BaseTool
from tools.models import ToolResult

from tools.protocols import (
    SecurityEngineProtocol,
    SanitizerProtocol,
    CommandExecutorProtocol,
)

# ── Default implementations (lazy-loaded from core/) ──────────────────────
# These provide backward compatibility when callers do NOT inject custom
# engines. They are imported lazily so the tools/ package never forces
# the core/ module graph to load at import time.


def _default_security() -> SecurityEngineProtocol:
    from core.security import validate

    return _LazySecurityEngine(validate)


def _default_sanitizer() -> SanitizerProtocol:
    from core.sanitize import sanitize

    return _LazySanitizer(sanitize)


def _default_executor() -> CommandExecutorProtocol:
    from core.utils import safe_execute_command

    return _LazyCommandExecutor(safe_execute_command)


# ── Thin adapter wrappers (bridge Protocol → real functions) ─────────────

class _LazySecurityEngine:
    """Adapter wrapping core.security.validate into SecurityEngineProtocol."""

    __slots__ = ("_fn",)

    def __init__(self, fn) -> None:
        self._fn = fn

    def validate(self, command: str) -> tuple[bool, str]:
        return self._fn(command)


class _LazySanitizer:
    """Adapter wrapping core.sanitize.sanitize into SanitizerProtocol."""

    __slots__ = ("_fn",)

    def __init__(self, fn) -> None:
        self._fn = fn

    def sanitize(
        self,
        text: str,
        *,
        strip_ansi: bool = False,
        strip_control: bool = False,
        preserve_tabs: bool = False,
        preserve_newlines: bool = False,
        redact_secrets_flag: bool = False,
    ) -> str:
        return self._fn(
            text,
            strip_ansi=strip_ansi,
            strip_control=strip_control,
            preserve_tabs=preserve_tabs,
            preserve_newlines=preserve_newlines,
            redact_secrets_flag=redact_secrets_flag,
        )


class _LazyCommandExecutor:
    """Adapter wrapping core.utils.safe_execute_command into CommandExecutorProtocol."""

    __slots__ = ("_fn",)

    def __init__(self, fn) -> None:
        self._fn = fn

    def safe_execute_command(self, command: str, timeout: int = 30) -> tuple[int, str, str]:
        return self._fn(command, timeout=timeout)


class ShellTool(BaseTool):
    """
    Execute Linux/Termux commands safely.

    Accepts optional Dependency Injection for security engine, sanitizer,
    and command executor. When omitted, default implementations from
    core/security, core/sanitize, and core/utils are lazily loaded.
    """

    name: Final[str] = "execute_shell"

    description: Final[str] = (
        "Execute safe non-interactive Linux/Termux shell commands. NOTE: Never run interactive scripts or REPLs that wait for stdin (e.g. 'python main.py') as they will time out. To run inline Python code, use 'python3 -c \"import ...\"'."
    )

    def __init__(
        self,
        security_engine: SecurityEngineProtocol | None = None,
        sanitizer: SanitizerProtocol | None = None,
        executor: CommandExecutorProtocol | None = None,
    ) -> None:
        self._security = security_engine if security_engine is not None else _default_security()
        self._sanitizer = sanitizer if sanitizer is not None else _default_sanitizer()
        self._executor = executor if executor is not None else _default_executor()

    def execute(self, **kwargs) -> ToolResult:
        command = kwargs.get("command")

        if not isinstance(command, str):
            return ToolResult(
                success=False,
                stderr="Missing or invalid 'command'.",
                returncode=-1,
                status="error"
            )

        command = command.strip()

        if not command:
            return ToolResult(
                success=False,
                stderr="Empty command.",
                returncode=-1,
                status="error"
            )

        # Security Validation (via injected engine)
        is_safe, reason = self._security.validate(command)

        if not is_safe:
            return ToolResult(
                success=False,
                stderr=f"Security validation failed: {reason}",
                returncode=-1,
                status="error"
            )

        try:
            returncode, stdout, stderr = self._executor.safe_execute_command(command)

            # Token-clamp outputs to protect the agent loop from terminal floods.
            MAX_SHELL_OUT = 8000
            stdout_str = self._sanitizer.sanitize(
                stdout.strip(), strip_ansi=True, preserve_newlines=True, redact_secrets_flag=True
            )
            if len(stdout_str) > MAX_SHELL_OUT:
                # Keep the tail: errors/results usually land there.
                stdout_str = f"... [STDOUT TRUNCATED] ...\n{stdout_str[-MAX_SHELL_OUT:]}"

            stderr_str = self._sanitizer.sanitize(
                stderr.strip(), strip_ansi=True, preserve_newlines=True, redact_secrets_flag=True
            )
            if len(stderr_str) > MAX_SHELL_OUT:
                stderr_str = f"... [STDERR TRUNCATED] ...\n{stderr_str[-MAX_SHELL_OUT:]}"

            return ToolResult(
                success=returncode == 0,
                stdout=stdout_str,
                stderr=stderr_str,
                returncode=returncode,
                status="success" if returncode == 0 else "error"
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                stderr=f"{type(exc).__name__}: {exc}",
                returncode=-1,
                status="error"
            )
