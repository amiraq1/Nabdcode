from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Any

from tools.base import BaseTool
from core.security import validate
from core.utils import safe_execute_command


from tools.models import ToolResult


class ShellTool(BaseTool):
    """
    Execute Linux/Termux commands safely.

    Depends on:
      - Security Validator
      - safe_execute_command() (without shell=True)
    """

    name: Final[str] = "execute_shell"

    description: Final[str] = (
        "Execute safe non-interactive Linux/Termux shell commands. NOTE: Never run interactive scripts or REPLs that wait for stdin (e.g. 'python main.py') as they will time out. To run inline Python code, use 'python3 -c \"import ...\"'."
    )

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

        # Security Validation
        is_safe, reason = validate(command)

        if not is_safe:
            return ToolResult(
                success=False,
                stderr=f"Security validation failed: {reason}",
                returncode=-1,
                status="error"
            )

        try:
            returncode, stdout, stderr = safe_execute_command(command)

            return ToolResult(
                success=returncode == 0,
                stdout=stdout.strip(),
                stderr=stderr.strip(),
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
