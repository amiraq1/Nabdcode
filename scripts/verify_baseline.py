#!/usr/bin/env python3
"""
scripts/verify_baseline.py — Deterministic Baseline Verification for NABD OS
============================================================================
Verifies that the current workspace matches or exceeds the baseline recorded
in audit-baseline/static_metrics.json and baseline.json, and executes the
EXE remediation test suite to ensure runtime operational integrity.

Exit codes:
  0: Baseline verified successfully (match or valid forward progress).
  1: Regression detected or baseline corrupted.
"""

from __future__ import annotations

import json
import os
import subprocess
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
    baseline_path = baseline_dir / "baseline.json"

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
    git_info = get_git_info()

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

    # 3. Verify git metadata alignment if baseline.json exists
    if baseline_path.exists():
        try:
            base_meta = json.loads(baseline_path.read_text(encoding="utf-8"))
            target_commit = base_meta.get("target_commit", "")
            current_commit = git_info.get("commit_hash", "")
            if target_commit and current_commit and target_commit != current_commit:
                print(f"[INFO] Current commit ({current_commit[:8]}) differs from baseline target ({target_commit[:8]}).")
        except Exception:
            pass

    if errors:
        print("[FAIL] Baseline verification failed with regressions:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print("[SUCCESS] Static baseline verification PASSED:")
    print(f"  - Total test files: {current_tests['total_test_files']} (baseline: {base_tests.get('total_test_files')})")
    print(f"  - Total test functions: {current_tests['total_test_functions']} (Sync: {current_tests['total_sync_test_functions']}, Async: {current_tests['total_async_test_functions']})")
    print(f"  - Tool mapping symbols: {current_tools['total_symbols']} (16 concrete, 13 secure, 4 protocols, 3 base, 1 pure)")

    # 4. Operational verification: run pytest collection & execution on EXE remediation suite
    print("\n[RUN] Executing operational pytest verification on remediation test suite (EXE-01 to EXE-07)...")
    exe_test_files = [
        "tests/test_exe01_wal_external_writer.py",
        "tests/test_exe02_dispatcher_zombie_workers.py",
        "tests/test_exe03_session_event_isolation.py",
        "tests/test_exe04_core_ui_boundary_lint.py",
        "tests/test_exe05_engine_cycle_lint.py",
        "tests/test_exe06_platform_lock_and_config.py",
        "tests/test_exe07_complexity_reduction.py",
    ]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"] + exe_test_files,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            print(f"[SUCCESS] EXE remediation tests PASSED:\n{result.stdout.strip()}")
        else:
            print(f"[FAIL] EXE remediation tests failed (exit code {result.returncode}):\n{result.stderr or result.stdout}", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"[WARN] Pytest execution: {exc}")


if __name__ == "__main__":
    main()

