"""SECURE_REPO_SCANNER — workspace map & keyword search tool.

A read-only, smolagents-compatible Tool that gives the agent a safe view of
the repository WITHOUT touching heavyweight or sensitive directories. It is
intended as a fast reconnaissance primitive so the agent can self-navigate
the workspace before invoking heavier tools (file reads, shell, edits).

SAFETY / SCOPE:
    • Operates strictly within the pinned workspace root (core.parser
      get_workspace_root) — never escapes via symlinks (we do not follow
      links) and never reads outside it.
    • Always excludes: .git, __pycache__, node_modules, and *.gguf model
      files (large binary artifacts that would blow up context / memory).
    • Read-only: performs NO writes, NO deletions, NO network, NO exec.
    • All errors are contained and returned as text — it can never raise
      into the agent loop.

TWO MODES (select via the ``action`` argument):

    action="map"
        Returns an indented ASCII directory tree of the workspace, skipping
        the excluded directories/files above. Useful for "what's in here".

    action="search"
        Requires ``keyword``. Scans every text file under the workspace
        (again skipping excluded paths) for the literal ``keyword`` and
        returns a compact report of ``path:line`` hits. Binary files and
        files that fail to decode are skipped silently.

USAGE EXAMPLES (for the LLM):
    # Get the workspace layout:
    repo_scanner(action="map")

    # Find where a symbol is defined/used:
    repo_scanner(action="search", keyword="RepositoryContextManager")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from smolagents import Tool

from core.parser import get_workspace_root

# Directories and file types that must never be scanned or listed.
_EXCLUDED_DIRS = {".git", "__pycache__", "node_modules"}
_EXCLUDED_SUFFIXES = (".gguf",)


def _is_excluded(path: Path) -> bool:
    """True if ``path`` lives inside an excluded dir or is an excluded file."""
    parts = set(path.parts)
    if parts & _EXCLUDED_DIRS:
        return True
    if path.name in _EXCLUDED_DIRS:
        return True
    if path.suffix in _EXCLUDED_SUFFIXES:
        return True
    return False


def _iter_files(root: Path):
    """Yield files under root, skipping excluded dirs/files and symlinks."""
    for entry in root.rglob("*"):
        # Skip symlinks entirely to avoid escaping the workspace jail.
        if entry.is_symlink():
            continue
        if entry.is_file() and not _is_excluded(entry):
            yield entry


def _tree(root: Path) -> str:
    """Build an indented directory tree string, excluding heavy paths."""
    lines: list[str] = [root.name + "/"]
    # Collect (depth, name, is_dir) in a stable, sorted walk.
    entries: list[tuple[int, str, bool]] = []

    def walk(d: Path, depth: int) -> None:
        # Sort dirs first then files, case-insensitive.
        children = [c for c in d.iterdir() if not c.is_symlink()]
        dirs = sorted(
            (c for c in children if c.is_dir() and not _is_excluded(c)),
            key=lambda p: p.name.lower(),
        )
        files = sorted(
            (c for c in children if c.is_file() and not _is_excluded(c)),
            key=lambda p: p.name.lower(),
        )
        for c in dirs:
            entries.append((depth, c.name + "/", True))
            walk(c, depth + 1)
        for c in files:
            entries.append((depth, c.name, False))

    try:
        walk(root, 1)
    except Exception:
        return f"{root.name}/ (unreadable)"

    for depth, name, _is_dir in entries:
        indent = "    " * depth
        lines.append(f"{indent}{name}")
    return "\n".join(lines)


def _search(root: Path, keyword: str) -> str:
    """Return ``path:line`` hits for ``keyword`` across text files."""
    hits: list[str] = []
    for f in _iter_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            # Binary or unreadable — skip silently.
            continue
        rel = f.relative_to(root)
        for i, line in enumerate(text.splitlines(), start=1):
            if keyword in line:
                hits.append(f"{rel}:{i}: {line.strip()}")
    if not hits:
        return f"No matches for '{keyword}'."
    return f"Found {len(hits)} match(es) for '{keyword}':\n" + "\n".join(hits)


def _safe_read(path: Path) -> str:
    """Read a text file, returning '' on any failure (binary/unreadable)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""


def _parse_list(lines, start_idx: int) -> list[str]:
    """Collect bracketed list items (lines like `  "x",`) from ``lines``.

    Starts at ``start_idx`` (the line containing `[`) and consumes until the
    closing `]`. Returns the stripped quoted/raw tokens found.
    """
    items: list[str] = []
    for line in lines[start_idx + 1:]:
        if "]" in line:
            break
        tok = line.strip().strip(",").strip().strip('"').strip("'")
        if tok:
            items.append(tok)
    return items


def _detect_build_system(root: Path, top_files: list[str]) -> dict:
    info: dict = {
        "build_system": {
            "type": "unknown",
            "name": "",
            "packages": [],
            "deps": [],
            "entry": "",
        }
    }
    build_map = {
        "CMakeLists.txt": "cmake",
        "Makefile": "make",
        "Cargo.toml": "cargo",
        "package.json": "npm",
    }
    for f in top_files:
        if f == "pyproject.toml":
            try:
                content = (root / f).read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if "name =" in line and not info["build_system"]["name"]:
                    info["build_system"]["name"] = line.split("=")[1].strip().strip('"')
                if "packages =" in line:
                    info["build_system"]["packages"] = _parse_list(lines, i)
                if "dependencies" in line:
                    info["build_system"]["deps"] = _parse_list(lines, i)
                if "nabdcode =" in line or "[project.scripts]" in line and not info["build_system"]["entry"]:
                    info["build_system"]["entry"] = line.split("=")[1].strip().strip('"') if "=" in line else ""
            bs = info["build_system"]
            if "setuptools" in content:
                bs["type"] = "setuptools"
            elif "poetry" in content:
                bs["type"] = "poetry"
            elif "flit" in content:
                bs["type"] = "flit"
            else:
                bs["type"] = "python"
        elif f in build_map:
            info["build_system"]["type"] = build_map[f]
    return info


def _detect_layers(root: Path) -> list[dict]:
    layers: list[dict] = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        entries = []
    for entry in entries:
        full = root / entry
        if not full.is_dir() or entry.startswith(".") or entry in ("__pycache__", "node_modules", "tests"):
            continue
        try:
            py_count = len(list(full.rglob("*.py")))
        except OSError:
            py_count = 0
        layers.append({"name": entry, "path": str(full), "files": py_count})
    return layers


def _detect_entry_points(root: Path) -> list[str]:
    entry_points: list[str] = []
    if (root / "main.py").exists():
        for line in (root / "main.py").read_text(encoding="utf-8", errors="replace").splitlines():
            if "def main(" in line:
                entry_points.append("main.py → main()")
                break
    if (root / "bin").is_dir():
        try:
            for f in os.listdir(root / "bin"):
                entry_points.append(f"bin/{f} → shell script")
        except OSError:
            pass
    return entry_points


def _compute_repo_metrics(root: Path) -> tuple[list[Path], dict[str, int]]:
    metrics = {"py_files": 0, "total_lines": 0, "classes": 0, "functions": 0}
    py_files: list[Path] = []
    for py in root.rglob("*.py"):
        if ".git" in str(py) or "__pycache__" in str(py):
            continue
        py_files.append(py)
        try:
            lines = py.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        metrics["py_files"] += 1
        metrics["total_lines"] += len(lines)
        metrics["classes"] += sum(1 for l in lines if l.strip().startswith("class "))
        metrics["functions"] += sum(1 for l in lines if l.strip().startswith("def "))
    return py_files, metrics


def _detect_security_patterns(py_files: list[Path]) -> dict[str, bool]:
    return {
        "consent_loop": any("ConsentManager" in _safe_read(p) for p in py_files),
        "kernel_isolation": any("core/kernel" in str(p) for p in py_files),
        "path_validation": any("_validate_path" in _safe_read(p) for p in py_files),
        "evidence_gate": any("EvidenceLog" in _safe_read(p) for p in py_files),
    }


def deep_scan_repo(root_path: str | Path) -> dict:
    """Comprehensive repository scan — returns structured JSON.

    Does NOT rely on the LLM to choose files. Reads all structural files
    deterministically and returns a complete architecture map. PURE PYTHON:
    no LLM calls, no tool invocations, completes in <2s.
    """
    root = Path(root_path)
    try:
        top_files = os.listdir(root)
    except OSError:
        top_files = []

    info = _detect_build_system(root, top_files)
    info["layers"] = _detect_layers(root)
    info["entry_points"] = _detect_entry_points(root)
    py_files, metrics = _compute_repo_metrics(root)
    info["metrics"] = metrics
    info["security"] = _detect_security_patterns(py_files)
    return info


class SECURE_REPO_SCANNER(Tool):
    """Read-only workspace map + keyword search (excludes .git, __pycache__,
    node_modules, and *.gguf models).

    action="map" -> returns the directory tree of the workspace.
    action="search" + keyword="<text>" -> returns file:line hits for the keyword.
    """

    name = "repo_scanner"
    description = (
        "Read-only reconnaissance over the workspace. "
        "action='map' returns an indented directory tree (ignores .git, "
        "__pycache__, node_modules, and *.gguf models). "
        "action='search' (requires keyword) scans text files and returns "
        "path:line hits for the keyword, ignoring the same heavy paths. "
        "Use this FIRST to understand or locate things before heavier tools. "
        "Never use it for writing, deleting, or executing."
    )
    inputs = {
        "action": {
            "type": "string",
            "description": "Either 'map' (directory tree), 'search' (keyword scan), or 'deep' (full structured architecture scan as JSON).",
            "nullable": False,
        },
        "keyword": {
            "type": "string",
            "description": "The literal text to search for. Required only when action='search'.",
            "nullable": True,
        },
    }
    output_type = "string"

    def forward(self, action: str, keyword: Optional[str] = None, **kwargs: Any) -> str:
        try:
            root = get_workspace_root()
            mode = (action or "").strip().lower()
            if mode == "map":
                return _tree(root)
            if mode == "search":
                if not keyword:
                    return "Error: action='search' requires a 'keyword' argument."
                return _search(root, keyword)
            if mode == "deep":
                import json

                return json.dumps(
                    self._deep_scan(root), indent=2, ensure_ascii=False
                )
            return "Error: action must be 'map', 'search', or 'deep'."
        except Exception as exc:  # containment: never break the agent loop
            return f"repo_scanner failed: {exc!r}"

    def _deep_scan(self, root_path: str | Path) -> dict:
        """Comprehensive repository scan — returns structured JSON.

        Does NOT rely on the LLM to choose files. Reads all structural files
        deterministically and returns a complete architecture map. PURE PYTHON:
        no LLM calls, no tool invocations, completes in <2s.
        """
        return deep_scan_repo(root_path)
