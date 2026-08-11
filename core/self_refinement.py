"""Stage 7 — Self-Refinement & Sandbox Testing.

Validates generated payloads with AST checks and executes them in a dedicated
worker process. The agent process never executes generated code directly.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from core.kernel.subprocess_guard import default_guard


class SafeExecutionSandbox:
    """Process-isolated boundary for safe code smoke-testing."""

    _ALLOWED_MODULES = {"json", "math", "statistics"}
    _FORBIDDEN_NAMES = {
        "__import__", "compile", "eval", "exec", "input", "open",
        "breakpoint", "exit", "globals", "locals", "vars", "getattr",
        "setattr", "delattr", "__builtins__",
    }
    _FORBIDDEN_ATTRIBUTES = {
        "chmod", "chown", "fork", "kill", "popen", "read_bytes", "read_text",
        "remove", "rmdir", "rmtree", "system", "unlink", "write_bytes",
        "write_text", "__subclasses__", "__globals__", "__builtins__", "__class__",
    }

    @classmethod
    def _validate_code(cls, code_str: str) -> tuple[bool, str]:
        try:
            tree = ast.parse(code_str, filename="<sandbox>")
        except (SyntaxError, ValueError) as exc:
            return False, f"CompileError: {exc}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in cls._FORBIDDEN_NAMES:
                return False, f"Forbidden name '{node.id}'"
            if isinstance(node, ast.Attribute) and node.attr in cls._FORBIDDEN_ATTRIBUTES:
                return False, f"Forbidden attribute '{node.attr}'"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] not in cls._ALLOWED_MODULES:
                        return False, f"Forbidden module '{alias.name}'"
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] not in cls._ALLOWED_MODULES:
                    return False, f"Forbidden module '{node.module}'"
        return True, ""

    @classmethod
    def _run_worker(cls, script_path: Path, *worker_args: str, timeout: float) -> dict:
        result = default_guard.run_infra(
            [sys.executable, str(Path(__file__).with_name("sandbox_worker.py")), str(script_path), *worker_args],
            cwd=str(script_path.parent),
            timeout=timeout,
            env={"PATH": "/usr/bin:/bin"},
        )
        if result[0] != 0:
            return {"passed": False, "error": result[2] or result[1] or "sandbox worker failed"}
        try:
            return json.loads(result[1])
        except json.JSONDecodeError as exc:
            return {"passed": False, "error": f"Invalid worker response: {exc}"}

    @classmethod
    def smoke_test_code(cls, code_str: str) -> Dict[str, Any]:
        """Validate and execute *code_str* in a separate worker process."""
        if not isinstance(code_str, str):
            return {"passed": False, "error": "code must be a string"}
        valid, reason = cls._validate_code(code_str)
        if not valid:
            return {"passed": False, "error": reason}

        with tempfile.TemporaryDirectory(prefix="nabd-sandbox-") as temp_dir:
            script_path = Path(temp_dir) / "payload.py"
            script_path.write_text(code_str, encoding="utf-8")
            return cls._run_worker(script_path, timeout=15.0)

    @classmethod
    def evaluate_code_suite(
        cls, code_str: str, test_cases: list[dict[str, Any]], timeout: float = 5.0
    ) -> Dict[str, Any]:
        """Evaluate a payload in a worker process and return JSON-safe results."""
        valid, reason = cls._validate_code(code_str)
        if not valid:
            return {"passed": False, "error": reason, "details": []}

        with tempfile.TemporaryDirectory(prefix="nabd-suite-") as temp_dir:
            root = Path(temp_dir)
            script_path = root / "payload.py"
            cases_path = root / "cases.json"
            script_path.write_text(code_str, encoding="utf-8")
            cases_path.write_text(json.dumps(test_cases), encoding="utf-8")
            return cls._run_worker(
                script_path,
                "suite",
                "solution",
                str(cases_path),
                timeout=timeout,
            )
