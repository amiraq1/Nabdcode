from __future__ import annotations

import contextlib
import io
import json
import runpy
import sys
import traceback
from pathlib import Path


def _load_namespace(script_path: str) -> dict:
    return runpy.run_path(script_path, run_name="__sandbox__")


def _find_target(namespace: dict, name: str) -> object | None:
    target = namespace.get(name)
    if callable(target):
        return target
    for value in namespace.values():
        if callable(value) and getattr(value, "__module__", None) == "__sandbox__":
            return value
    return None


def _invoke(target: object, inputs: object) -> object:
    if isinstance(inputs, dict):
        return target(**inputs)
    if isinstance(inputs, (list, tuple)):
        return target(*inputs)
    return target(inputs)


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"passed": False, "error": "missing script path"}))
        return 2

    script_path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "smoke"
    try:
        if mode == "smoke":
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                _load_namespace(script_path)
            print(json.dumps({"passed": True, "error": None, "stdout": output.getvalue()}))
            return 0

        if len(sys.argv) < 4:
            print(json.dumps({"passed": False, "error": "missing target or cases"}))
            return 2
        target_name = sys.argv[3]
        cases = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
        namespace = _load_namespace(script_path)
        target = _find_target(namespace, target_name)
        if target is None:
            raise NameError("no testable function found in payload")

        details = []
        for index, case in enumerate(cases, start=1):
            try:
                actual = _invoke(target, case.get("inputs"))
                expected = case.get("expected")
                passed = actual == expected
                details.append({
                    "case": index,
                    "status": "passed" if passed else "failed",
                    "error": None if passed else f"mismatch: expected {expected!r}, got {actual!r}",
                    "expected": expected,
                    "actual": actual,
                })
            except Exception as exc:
                details.append({
                    "case": index,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "expected": case.get("expected"),
                    "actual": None,
                })
        print(json.dumps({"passed": True, "details": details}, default=repr))
        return 0
    except Exception as exc:
        print(json.dumps({
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=4),
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
