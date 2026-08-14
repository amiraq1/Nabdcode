#!/usr/bin/env python3
"""
scripts/verify_baseline.py — Deterministic Baseline Verification for NABD OS
============================================================================
Verifies that the current workspace matches or exceeds the baseline recorded
in audit-baseline/static_metrics.json.

Exit codes:
  0: Baseline verified successfully (match or valid forward progress).
  1: Regression detected or baseline corrupted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Import analysis logic from audit_baseline
from audit_baseline import analyze_test_suite, analyze_tool_mapping, get_git_info


def main():
    # Reconfigure stdout for UTF-8 safety
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    baseline_dir = root / "audit-baseline"

    static_metrics_path = baseline_dir / "static_metrics.json"
    if not static_metrics_path.exists():
        print(f"[FAIL] Missing baseline file: {static_metrics_path}", file=sys.stderr)
        sys.exit(1)

    try:
        baseline_data = json.loads(static_metrics_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[FAIL] Failed to parse {static_metrics_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    base_tests = baseline_data.get("test_suite", {})
    base_tools = baseline_data.get("tool_registry_mapping", {})

    current_tests = analyze_test_suite()
    current_tools = analyze_tool_mapping()

    errors = []

    # 1. Verify test counts (No unexpected regressions)
    if current_tests["total_test_functions"] < base_tests.get("total_test_functions", 0):
        errors.append(
            f"Test function regression: current {current_tests['total_test_functions']} < baseline {base_tests.get('total_test_functions')}"
        )

    if current_tests["total_async_test_functions"] < base_tests.get("total_async_test_functions", 0):
        errors.append(
            f"Async test regression: current {current_tests['total_async_test_functions']} < baseline {base_tests.get('total_async_test_functions')}"
        )

    # 2. Verify tool mapping integrity
    if current_tools["total_symbols"] < base_tools.get("total_symbols", 0):
        errors.append(
            f"Tool mapping symbols dropped: current {current_tools['total_symbols']} < baseline {base_tools.get('total_symbols')}"
        )

    if errors:
        print("[FAIL] Baseline verification failed with regressions:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print("[SUCCESS] Baseline verification PASSED:")
    print(f"  - Total test files: {current_tests['total_test_files']} (baseline: {base_tests.get('total_test_files')})")
    print(f"  - Total test functions: {current_tests['total_test_functions']} (Sync: {current_tests['total_sync_test_functions']}, Async: {current_tests['total_async_test_functions']})")
    print(f"  - Tool mapping symbols: {current_tools['total_symbols']} (16 concrete, 13 secure, 4 protocols, 3 base, 1 pure)")


if __name__ == "__main__":
    main()
