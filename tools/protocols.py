# tools/protocols.py
"""Abstract Protocols for Dependency Inversion in the Tools layer.

These Protocols define the contracts that engine-layer services must satisfy
so the tools/ package never needs to import core/ directly at module load.
Every tool that needs security validation, sanitization, or command execution
accepts these interfaces via constructor Dependency Injection instead.

The concrete implementations are provided by core/ modules and wired at
startup (see core/agent_manager.py, core/app_context.py).

Usage:

    class SecureShellTool(BaseTool):
        def __init__(
            self,
            security_engine: SecurityEngineProtocol | None = None,
            sanitizer: SanitizerProtocol | None = None,
            executor: CommandExecutorProtocol | None = None,
        ) -> None:
            self._security = security_engine or _default_security()
            self._sanitizer = sanitizer or _default_sanitizer()
            self._executor = executor or _default_executor()
"""

from __future__ import annotations

from typing import Any, Optional, Protocol


class SecurityEngineProtocol(Protocol):
    """Contract for shell command validation.

    Mirrors core/security.validate(command) → tuple[bool, str].
    """

    def validate(self, command: str) -> tuple[bool, str]:
        """Validate a shell command.

        Returns (is_safe: bool, reason: str).
        If is_safe is True, reason is a human-readable confirmation.
        If is_safe is False, reason describes the violation.
        """
        ...


class SanitizerProtocol(Protocol):
    """Contract for text sanitization.

    Mirrors core/sanitize.sanitize(text, ...).
    """

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
        """Sanitize a string by stripping ANSI, control chars, etc.

        Must be idempotent — calling sanitize twice produces the same
        result as calling it once.
        """
        ...


class CommandExecutorProtocol(Protocol):
    """Contract for safe shell command execution.

    Mirrors core/utils.safe_execute_command(command, timeout).
    """

    def safe_execute_command(
        self, command: str, timeout: int = 30
    ) -> tuple[int, str, str]:
        """Execute a shell command securely without shell=True.

        Returns (returncode: int, stdout: str, stderr: str).
        Must NOT raise on execution failure — return non-zero returncode
        and populate stderr instead.
        """
        ...


class PermissionEngineProtocol(Protocol):
    """Contract for runtime permission checks.

    Mirrors core/permissions.PermissionEngine.check_access().
    """

    def check_access(self, action: str, resource: str) -> bool:
        """Check whether the agent is authorised for the given action/resource.

        Returns True if allowed, False if denied.
        """
        ...
