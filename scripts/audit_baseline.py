#!/usr/bin/env python3
"""
scripts/audit_baseline.py — Canonical Baseline Generator for NABD OS
===================================================================
Generates deterministic baseline artifacts under audit-baseline/:
  1. baseline.json: Environment, Git metadata, OS, Python version.
  2. static_metrics.json: Exact AST counts (FunctionDef, AsyncFunctionDef, Test Classes, Tool Mapping).
  3. failure_manifest.json: Platform constraints & fail-closed execution manifest.
"""

from __future__ import annotations

import ast
import glob
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def get_git_info() -> dict:
    def _run_git(args: list[str]) -> str:
        try:
            res = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout.strip()
        except Exception:
            return "UNKNOWN"

    commit_hash = _run_git(["rev-parse", "HEAD"])
    branch = _run_git(["branch", "--show-current"])
    status = _run_git(["status", "-s"])
    is_dirty = len(status.strip()) > 0

    return {
        "commit_hash": commit_hash,
        "branch": branch,
        "is_dirty": is_dirty,
    }


def analyze_test_suite() -> dict:
    test_files = sorted(glob.glob("tests/**/test_*.py", recursive=True))
    sync_tests = []
    async_tests = []
    test_classes = []

    for f_path in test_files:
        normalized_path = Path(f_path).as_posix()
        try:
            with open(f_path, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read(), filename=f_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
                    async_tests.append({
                        "file": normalized_path,
                        "name": node.name,
                        "lineno": node.lineno,
                    })
                elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    sync_tests.append({
                        "file": normalized_path,
                        "name": node.name,
                        "lineno": node.lineno,
                    })
                elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                    test_classes.append({
                        "file": normalized_path,
                        "name": node.name,
                        "lineno": node.lineno,
                    })
        except Exception as exc:
            print(f"⚠️ Error parsing {f_path}: {exc}", file=sys.stderr)

    return {
        "total_test_files": len(test_files),
        "total_sync_test_functions": len(sync_tests),
        "total_async_test_functions": len(async_tests),
        "total_test_functions": len(sync_tests) + len(async_tests),
        "total_test_classes": len(test_classes),
        "async_test_details": async_tests,
    }


def analyze_tool_mapping() -> dict:
    tool_init = Path("tools/__init__.py")
    if not tool_init.exists():
        return {"error": "tools/__init__.py not found"}

    with open(tool_init, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(tool_init))

    tool_mapping = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_TOOL_MAPPING":
                    if isinstance(node.value, ast.Dict):
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                                tool_mapping[k.value] = v.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "_TOOL_MAPPING":
                if isinstance(node.value, ast.Dict):
                    for k, v in zip(node.value.keys, node.value.values):
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                            tool_mapping[k.value] = v.value

    # Categorize symbols
    concrete_tools = [
        "ShellTool", "FileSystemTool", "WebSearchTool", "SearchMemoryTool",
        "TodoWriteTool", "RagSearchTool", "TermuxMonitorTool", "TaskTool",
        "BrowserTool", "GitTool", "GitPushTool", "CodeIntelligenceTool",
        "PythonREPLTool", "TasteManagerTool", "GraphifyTool", "GraphIntelTool"
    ]
    secure_wrappers = [
        "SecureTool", "SecureShellTool", "SecureFileSystemTool", "SecureWebSearchTool",
        "SecureBrowserTool", "SecureWorkspaceReader", "SecureGitInspector",
        "SecureTestRunner", "SecureSemanticMemoryTool", "SecureCodeIntelligenceTool",
        "SecurePythonREPLTool", "SecureTasteManagerTool", "SecureGraphifyTool"
    ]
    protocols = [
        "SecurityEngineProtocol", "SanitizerProtocol", "CommandExecutorProtocol",
        "PermissionEngineProtocol"
    ]
    base_models = ["BaseTool", "ToolResult", "FileAction"]
    pure_functions = ["execute_search_memory"]

    return {
        "total_symbols": len(tool_mapping),
        "concrete_tools_count": len([k for k in tool_mapping if k in concrete_tools]),
        "secure_wrappers_count": len([k for k in tool_mapping if k in secure_wrappers]),
        "protocols_count": len([k for k in tool_mapping if k in protocols]),
        "base_and_models_count": len([k for k in tool_mapping if k in base_models]),
        "pure_functions_count": len([k for k in tool_mapping if k in pure_functions]),
        "symbols": tool_mapping,
    }


def main():
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    out_dir = root / "audit-baseline"
    out_dir.mkdir(exist_ok=True)

    git_info = get_git_info()
    test_metrics = analyze_test_suite()
    tool_metrics = analyze_tool_mapping()

    baseline_data = {
        "baseline_version": "1.0.0",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_commit": git_info["commit_hash"],
        "target_branch": git_info["branch"],
        "working_tree_dirty": git_info["is_dirty"],
        "host_platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
        },
        "target_runtime_os": "Linux / Android (Termux) POSIX",
    }

    static_metrics_data = {
        "commit": git_info["commit_hash"],
        "test_suite": test_metrics,
        "tool_registry_mapping": tool_metrics,
    }

    failure_manifest_data = {
        "commit": git_info["commit_hash"],
        "policy": "Fail-closed — No silent skips permitted on core invariants",
        "documented_platform_constraints": [
            {
                "constraint_id": "PLAT-01-FCNTL",
                "severity": "PORTABILITY_LIMITATION",
                "component": "core/accept_edits_state.py",
                "description": "Direct dependency on POSIX 'fcntl.flock' for WAL journal cross-process concurrency. Dynamic import / collection on Windows raises ModuleNotFoundError.",
                "remediation_status": "Planned for PR-G (Cross-platform PlatformFileLock abstraction)",
            },
            {
                "constraint_id": "SEC-01-TOCTOU",
                "severity": "DOCUMENTED_LOW",
                "component": "core/project_root_guard.py",
                "description": "TOCTOU race window during file access checks; documented in docs/known_limitations.md.",
                "remediation_status": "Documented limitation; openat(O_NOFOLLOW) roadmap item",
            },
            {
                "constraint_id": "RT-01-REGEX-CLAIM",
                "severity": "DOCUMENTED_LOW_MEDIUM",
                "component": "core/verifier.py",
                "description": "Numeric test claim regex can be bypassed by non-matching NLP phrasing without L2 SemanticVerifier.",
                "remediation_status": "Documented in docs/threat_model.md §5",
            },
        ],
    }

    # Save outputs
    (out_dir / "baseline.json").write_text(json.dumps(baseline_data, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "static_metrics.json").write_text(json.dumps(static_metrics_data, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "failure_manifest.json").write_text(json.dumps(failure_manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Reconfigure stdout for UTF-8 safety
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("[SUCCESS] Baseline generated successfully under audit-baseline/:")
    print(f"   - baseline.json ({git_info['commit_hash'][:8]})")
    print(f"   - static_metrics.json ({test_metrics['total_test_functions']} test functions, {tool_metrics['total_symbols']} tool symbols)")
    print(f"   - failure_manifest.json ({len(failure_manifest_data['documented_platform_constraints'])} documented constraints)")


if __name__ == "__main__":
    main()
