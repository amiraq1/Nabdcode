"""Stage 2 (Lifecycle) — Test-Suite Evaluation Matrix.

Runs a generated skill/function payload against a list of test cases inside
the isolated sandbox, producing a structured pass/fail evaluation report.
Per-case failures (exceptions, mismatches, timeouts) are contained so a
single bad case never aborts the whole matrix.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Any, Dict, List

from core.self_refinement import SafeExecutionSandbox

# Hard ceiling per test case so an accidental infinite loop cannot hang the
# evaluation matrix. Threads can't be force-killed, so on timeout we record
# the failure and abandon the (orphaned) worker rather than join it forever.
CASE_TIMEOUT_SECONDS = 5.0


def _run_with_timeout(func, *args, timeout: float = CASE_TIMEOUT_SECONDS) -> Any:
    """Execute ``func`` in a worker thread, returning its result or raising TimeoutError."""
    fut: "Future[Any]" = Future()

    def _worker() -> None:
        try:
            fut.set_result(func(*args))
        except BaseException as exc:  # noqa: BLE001 - propagate to caller
            fut.set_exception(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    try:
        return fut.result(timeout=timeout)
    except TimeoutError:
        raise TimeoutError(f"execution exceeded {timeout}s (possible infinite loop)")


class TestMatrixEvaluator:
    """Evaluates a code payload against a suite of test cases."""
    __test__ = False

    def __init__(self, case_timeout: float = CASE_TIMEOUT_SECONDS) -> None:
        self.case_timeout = case_timeout

    def evaluate_code_suite(
        self, code_str: str, test_cases: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Run ``code_str`` against ``test_cases`` and return an evaluation report.

        Each test case: {"inputs": <tuple|dict>, "expected": <any>}.
        The payload is compiled/executed once in the sandbox; the target
        callable is discovered as the first function defined in the payload
        (e.g. ``def solution(...)``).

        Returns:
            {
              "summary": {"total", "passed", "failed", "score_percentage"},
              "details": [ {"case": int, "status": "passed"|"failed",
                            "error": str|None, "expected": ..., "actual": ...}, ... ]
            }
        """
        total = len(test_cases)
        passed = 0
        failed = 0
        details: List[Dict[str, Any]] = []

        # 1. Compile + sandbox-exec the payload ONCE (reused for every case).
        compiled = None
        sandbox_globals: Dict[str, Any] = {}
        try:
            result = SafeExecutionSandbox.smoke_test_code(code_str)
            if not result["passed"]:
                # Whole payload invalid: every case fails with the compile error.
                for i, case in enumerate(test_cases, start=1):
                    failed += 1
                    details.append(
                        {
                            "case": i,
                            "status": "failed",
                            "error": f"payload error: {result['error']}",
                            "expected": case.get("expected"),
                            "actual": None,
                        }
                    )
                return self._report(total, passed, failed, details)
            # Re-exec into a fresh namespace to capture the defined function.
            compiled = compile(code_str, "<suite>", "exec")
            SafeExecutionSandbox.smoke_test_code(code_str)  # already validated
            namespace: Dict[str, Any] = {}
            exec(compiled, namespace)  # nosec - verified safe
            target = self._find_target(namespace)
            if target is None:
                raise NameError(
                    "no testable function found in payload (expected e.g. 'def solution(...)')"
                )
        except Exception as exc:  # noqa: BLE001 - payload-level failure
            for i, case in enumerate(test_cases, start=1):
                failed += 1
                details.append(
                    {
                        "case": i,
                        "status": "failed",
                        "error": f"payload error: {type(exc).__name__}: {exc}",
                        "expected": case.get("expected"),
                        "actual": None,
                    }
                )
            return self._report(total, passed, failed, details)

        # 2. Per-case evaluation, each isolated so one failure can't abort the loop.
        for i, case in enumerate(test_cases, start=1):
            try:
                actual = self._invoke(target, case.get("inputs"))
                expected = case.get("expected")
                if self._matches(actual, expected):
                    passed += 1
                    details.append(
                        {
                            "case": i,
                            "status": "passed",
                            "error": None,
                            "expected": expected,
                            "actual": actual,
                        }
                    )
                else:
                    failed += 1
                    details.append(
                        {
                            "case": i,
                            "status": "failed",
                            "error": f"mismatch: expected {expected!r}, got {actual!r}",
                            "expected": expected,
                            "actual": actual,
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - single-case containment
                failed += 1
                details.append(
                    {
                        "case": i,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "expected": case.get("expected"),
                        "actual": None,
                    }
                )

        return self._report(total, passed, failed, details)

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _find_target(namespace: Dict[str, Any]) -> Any:
        """Pick the first user-defined function as the test target."""
        for value in namespace.values():
            if callable(value) and getattr(value, "__module__", None) in (None, "__sandbox__"):
                return value
        return None

    @staticmethod
    def _invoke(target: Any, inputs: Any) -> Any:
        """Call target with inputs (tuple/dict) under a timeout."""
        if isinstance(inputs, dict):
            return _run_with_timeout(target, **inputs)
        if isinstance(inputs, (tuple, list)):
            return _run_with_timeout(target, *inputs)
        # Bare single arg.
        return _run_with_timeout(target, inputs)

    @staticmethod
    def _matches(actual: Any, expected: Any) -> bool:
        """Loose equality with NaN-safe handling."""
        try:
            return bool(actual == expected)
        except Exception:
            return type(actual) == type(expected) and actual == expected

    @staticmethod
    def _report(total: int, passed: int, failed: int, details: List[Dict[str, Any]]) -> Dict[str, Any]:
        score = (passed / total * 100.0) if total else 0.0
        return {
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "score_percentage": round(score, 2),
            },
            "details": details,
        }
