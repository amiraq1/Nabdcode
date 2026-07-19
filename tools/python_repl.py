# tools/python_repl.py
"""
Python REPL Tool — secure, AST-hardened, zero-dependency execution sandbox tailored for Termux / Edge environments.

Provides:
  • PythonREPLTool — executes Python snippets inside .nabd/sandbox with AST security filtering and circuit-breaking timeouts.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path
from typing import Any, Final, Optional, Tuple, Type

from tools.base import BaseModel, BaseTool, Field
from tools.models import ToolResult


class PythonREPLArgs(BaseModel):
    """Pydantic schema for PythonREPLTool arguments."""
    code: str = Field(..., description="The valid Python script to execute. Use print() to output results.")


class PythonREPLTool(BaseTool):
    """A Python execution shell inside a secure sandbox directory (.nabd/sandbox).

    Includes AST safety verification and a 15-second circuit breaker for infinite loops.
    """

    name: Final[str] = "python_repl"
    description: Final[str] = (
        "A Python shell for executing code. Useful for math, data analysis, and logic testing. "
        "You MUST use print() to see the output. Execution happens in an isolated .nabd/sandbox directory."
    )
    inputs: dict = {
        "code": {
            "type": "string",
            "description": "The valid Python script to execute. Use print() to output results.",
        },
    }

    # Commands and modules that could damage or compromise the edge system/workspace
    FORBIDDEN_CALLS: Final[set[str]] = {
        "system", "rmtree", "remove", "unlink", "popen",
        "execl", "execv", "fork", "kill", "rmdir", "chmod", "chown",
    }
    FORBIDDEN_MODULES: Final[set[str]] = {
        "subprocess", "ctypes",
    }

    def __init__(self, workspace: str | Path = ".", timeout: float = 15.0) -> None:
        self.workspace = Path(workspace).resolve()
        self.sandbox_dir = self.workspace / ".nabd" / "sandbox"
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return PythonREPLArgs

    def _is_safe_code(self, code: str) -> Tuple[bool, str]:
        """Inspect AST to prevent destructive system calls or dangerous module imports."""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in self.FORBIDDEN_CALLS:
                    return False, f"Code contains forbidden attribute/method call '{node.attr}' for safety."
                if isinstance(node, ast.Name) and node.id in self.FORBIDDEN_CALLS:
                    return False, f"Code contains forbidden system call '{node.id}' for safety."
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_mod = alias.name.split(".")[0]
                        if top_mod in self.FORBIDDEN_MODULES:
                            return False, f"Code imports forbidden module '{alias.name}' for safety."
                if isinstance(node, ast.ImportFrom) and node.module:
                    top_mod = node.module.split(".")[0]
                    if top_mod in self.FORBIDDEN_MODULES:
                        return False, f"Code imports from forbidden module '{node.module}' for safety."
            return True, ""
        except SyntaxError:
            # Let actual execution handle syntax error so line number / traceback is returned
            return True, ""

    def execute(self, **kwargs) -> ToolResult:
        code = kwargs.get("code")
        if not isinstance(code, str) or not code.strip():
            return ToolResult(
                success=False,
                stderr="Missing or invalid 'code' argument.",
                returncode=-1,
                status="error",
            )

        is_safe, reason = self._is_safe_code(code)
        if not is_safe:
            return ToolResult(
                success=False,
                stderr=f"Execution Blocked: {reason}",
                returncode=-1,
                status="error",
            )

        script_path = self.sandbox_dir / "temp_execution.py"
        try:
            script_path.write_text(code, encoding="utf-8")
        except Exception as exc:
            return ToolResult(
                success=False,
                stderr=f"Failed to write script to sandbox: {exc}",
                returncode=-1,
                status="error",
            )

        try:
            result = subprocess.run(
                ["python3", str(script_path)],
                cwd=str(self.sandbox_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout,  # Circuit breaker
            )
            output = result.stdout + result.stderr
            if result.returncode == 0:
                final_out = output if output.strip() else "Code executed successfully with no output. (Did you forget to print()?)"
                return ToolResult(
                    success=True,
                    stdout=final_out,
                    stderr=result.stderr,
                    returncode=0,
                    metadata={"tool": self.name, "sandbox": str(self.sandbox_dir)},
                )
            else:
                return ToolResult(
                    success=False,
                    stdout=result.stdout,
                    stderr=result.stderr or "Execution Error",
                    returncode=result.returncode,
                    status="error",
                    metadata={"tool": self.name, "sandbox": str(self.sandbox_dir)},
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                stderr=f"Execution Error: Script timed out after {self.timeout} seconds. Possible infinite loop.",
                returncode=-1,
                status="error",
                metadata={"tool": self.name, "sandbox": str(self.sandbox_dir), "timeout": self.timeout},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                stderr=f"Execution Error: {exc}",
                returncode=-1,
                status="error",
            )

    def forward(self, code: str = "", **kwargs: Any) -> str:
        """smolagents / legacy string-only entry point."""
        code_to_run = code or kwargs.get("code", "")
        res = self.execute(code=code_to_run)
        if not res.success:
            return res.stderr or res.stdout or "Execution Error"
        return res.stdout
