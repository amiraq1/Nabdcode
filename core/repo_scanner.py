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

from pathlib import Path
from typing import Optional

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
            "description": "Either 'map' (directory tree) or 'search' (keyword scan).",
            "nullable": False,
        },
        "keyword": {
            "type": "string",
            "description": "The literal text to search for. Required only when action='search'.",
            "nullable": True,
        },
    }
    output_type = "string"

    def forward(self, action: str, keyword: Optional[str] = None) -> str:
        try:
            root = get_workspace_root()
            mode = (action or "").strip().lower()
            if mode == "map":
                return _tree(root)
            if mode == "search":
                if not keyword:
                    return "Error: action='search' requires a 'keyword' argument."
                return _search(root, keyword)
            return "Error: action must be 'map' or 'search'."
        except Exception as exc:  # containment: never break the agent loop
            return f"repo_scanner failed: {exc!r}"
