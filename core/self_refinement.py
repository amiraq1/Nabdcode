"""Stage 7 — Self-Refinement & Sandbox Testing.

Provides an isolated execution boundary that smoke-tests a generated code
payload for syntax and basic runtime stability before it reaches the
semantic/security VerifierAgent. Failures are captured cleanly (no blast
radius) so the orchestrator can route concrete technical errors back to the
CoderAgent for a self-correction rewrite loop.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import traceback
from typing import Any, Dict


class SafeExecutionSandbox:
    """Isolated boundary for safe code smoke-testing."""

    @staticmethod
    def smoke_test_code(code_str: str) -> Dict[str, Any]:
        """Compile + isolated-execute `code_str`, capturing any failure.

        Returns:
            {"passed": True, "error": None} on success, or
            {"passed": False, "error": "<traceback context>"} on failure.
        """
        # 1. Syntax/compile guard — cheapest, catches the majority of cases.
        try:
            compiled = compile(code_str, "<sandbox>", "exec")
        except (SyntaxError, ValueError) as exc:
            return {
                "passed": False,
                "error": f"CompileError: {exc}\n{traceback.format_exc(limit=4)}",
            }

        # 2. Isolated runtime guard — curated safe-builtin allowlist (no
        # open/eval/exec/__import__/input), captured IO. Legitimate code can
        # run; dangerous primitives are absent, so the blast radius is bounded.
        _dangerous = {
            "open", "eval", "exec", "compile", "__import__", "input",
            "exit", "quit", "help", "copyright", "license", "credits",
            "breakpoint", "memoryview", "super",
        }
        safe_builtins = {
            name: getattr(builtins, name)
            for name in dir(builtins)
            if name not in _dangerous and not name.startswith("_")
        }
        sandbox_globals: Dict[str, Any] = {
            "__builtins__": safe_builtins,
            "__name__": "__sandbox__",
        }
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                exec(compiled, sandbox_globals)  # isolated namespace
        except Exception as exc:
            return {
                "passed": False,
                "error": (
                    f"{type(exc).__name__}: {exc}\n"
                    f"{traceback.format_exc(limit=6)}"
                ),
            }

        return {"passed": True, "error": None}
