# core/diff_matrix.py
"""
High-Fidelity Diff Matrix Engine (File Change Visualization Subsystem).

Architectural DNA inspired by professional terminal diff renderers (The Diff Matrix / St):
  1. Display-Only Subsystem: Pure presentation computation decoupled from file mutation.
  2. Context Elision & Stats Pass: Computes added/removed line statistics and elides long
     unchanged regions to context_lines hunks.
  3. Verified Gaps Closed:
     - maxLines enforcement: Hard truncation boundary capping rendered lines to protect terminal.
     - permissionDenied branch: Renders an explicit permission-denied visual state.
     - filePath escaping: Sanitizes file paths before display against ANSI/control injection.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import List
from core.sanitize import sanitize


@dataclass(frozen=True)
class DiffMatrixResult:
    file_path: str
    added_count: int
    removed_count: int
    lines: List[str]
    is_truncated: bool = False
    permission_denied: bool = False

    @property
    def formatted_header(self) -> str:
        safe_path = sanitize(self.file_path, strip_ansi=True) if self.file_path else "Untitled"
        if self.permission_denied:
            return f"🔒 PERMISSION DENIED: {safe_path}"
        return f"📄 {safe_path} (+{self.added_count} / -{self.removed_count})"


def generate_diff(
    old_value: str = "",
    new_value: str = "",
    file_path: str = "",
    permission_denied: bool = False,
    max_lines: int = 400,
    context_lines: int = 3,
) -> DiffMatrixResult:
    """
    Generate structured diff matrix with stats, context elision, path sanitization,
    and maxLines truncation.
    """
    safe_path = sanitize(file_path, strip_ansi=True, strip_control=True)

    # 1. Permission Denied Branch
    if permission_denied:
        return DiffMatrixResult(
            file_path=safe_path,
            added_count=0,
            removed_count=0,
            lines=[
                f"🔒 Permission Denied: Unable to read or preview changes for '{safe_path}'."
            ],
            is_truncated=False,
            permission_denied=True,
        )

    old_lines = (old_value or "").splitlines()
    new_lines = (new_value or "").splitlines()

    # 2. Compute Unified Diff with context elision
    diff_generator = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{safe_path}" if safe_path else "a",
        tofile=f"b/{safe_path}" if safe_path else "b",
        n=context_lines,
        lineterm="",
    )

    raw_diff_lines = list(diff_generator)

    # 3. Stats pass: count added and removed lines (excluding headers)
    added_count = 0
    removed_count = 0
    for line in raw_diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            added_count += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed_count += 1

    # 4. Enforce maxLines truncation boundary
    is_truncated = False
    output_lines = raw_diff_lines
    if len(raw_diff_lines) > max_lines:
        is_truncated = True
        output_lines = raw_diff_lines[:max_lines]
        output_lines.append(
            f"... [DIFF TRUNCATED: Showing first {max_lines} of {len(raw_diff_lines)} lines] ..."
        )

    return DiffMatrixResult(
        file_path=safe_path,
        added_count=added_count,
        removed_count=removed_count,
        lines=output_lines,
        is_truncated=is_truncated,
        permission_denied=False,
    )
