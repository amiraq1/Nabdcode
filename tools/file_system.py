from __future__ import annotations

import difflib
from enum import Enum
from pathlib import Path
from typing import Final

from tools.base import BaseTool
from tools.models import ToolResult
from core.sanitize import sanitize


class FileAction(str, Enum):
    READ = "read"
    WRITE = "write"
    APPEND = "append"
    REPLACE = "replace"


MAX_DIFF_BYTES = 200 * 1024  # 200KB limit
MAX_DIFF_LINES = 1000


class FileSystemTool(BaseTool):
    """
    Safe local file system tool.

    Supported actions:
        - read
        - write
        - append
        - replace

    All operations are restricted to the configured workspace.
    """

    name: Final[str] = "file_system"

    description: Final[str] = (
        "Safely read, write, append, and replace text in files inside the workspace. "
        "Required args: 'action' ('read', 'write', 'append', 'replace'), 'path' (str). "
        "For write/append, pass 'content' (str). For replace, pass 'old_text' (str), 'new_text' (str), and optional 'count' (int, default 1) or 'all' (bool)."
    )

    MAX_READ_SIZE: Final[int] = 1_000_000  # 1 MB

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()

    def execute(self, **kwargs) -> ToolResult:

        action = kwargs.get("action")
        if not action and "mode" in kwargs:
            mode_map = {"r": "read", "rb": "read", "w": "write", "wb": "write", "a": "append", "ab": "append"}
            action = mode_map.get(str(kwargs.get("mode")).lower().strip(), "write")

        path = kwargs.get("path")
        content = kwargs.get("content", "")

        #
        # Validation
        #

        if not isinstance(action, str):
            return ToolResult(
                success=False,
                stderr="Missing required argument 'action'. Allowed values: 'read', 'write', 'append', 'replace'.",
            )

        if not isinstance(path, str):
            return ToolResult(
                success=False,
                stderr="Argument 'path' must be a string.",
            )

        action = action.lower().strip()

        try:
            action = FileAction(action)
        except ValueError:

            return ToolResult(
                success=False,
                stderr=(
                    "Unsupported action. "
                    "Allowed values: read, write, append, replace."
                ),
            )

        try:

            target = self._resolve(path)

            if action is FileAction.READ:
                return self._read(target)

            if action is FileAction.WRITE:
                return self._write(target, content)

            if action is FileAction.APPEND:
                return self._append(target, content)

            if action is FileAction.REPLACE:
                return self._replace(
                    target,
                    kwargs.get("old_text"),
                    kwargs.get("new_text", ""),
                    count=kwargs.get("count", 1),
                    replace_all=kwargs.get("all", kwargs.get("replace_all", False)),
                )

            return ToolResult(
                success=False,
                stderr="Unsupported operation.",
            )

        except PermissionError as exc:

            return ToolResult(
                success=False,
                stderr=str(exc),
            )

        except Exception as exc:

            return ToolResult(
                success=False,
                stderr=f"{type(exc).__name__}: {exc}",
            )

    # ------------------------------------------------------------------

    def _resolve(self, relative_path: str) -> Path:
        """
        Resolve a path safely inside the workspace.
        """

        target = (self.workspace / relative_path).resolve()

        if self.workspace not in target.parents and target != self.workspace:
            raise PermissionError(
                "Access outside the workspace is forbidden."
            )

        return target

    # ------------------------------------------------------------------

    def _read(self, path: Path) -> ToolResult:

        if not path.exists():

            return ToolResult(
                success=False,
                stderr=f"File not found: {path.name}",
            )

        if not path.is_file():

            return ToolResult(
                success=False,
                stderr="Target is not a file.",
            )

        if path.stat().st_size > self.MAX_READ_SIZE:

            return ToolResult(
                success=False,
                stderr="File is too large to read.",
            )

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        return ToolResult(
            success=True,
            stdout=sanitize(text, preserve_tabs=True, preserve_newlines=True),
        )

    # ------------------------------------------------------------------

    def _compute_diff(self, filename: str, old_content: str, new_content: str) -> tuple[str, int, int]:
        lines = list(difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3,
            lineterm=""
        ))
        additions = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))

        if len(lines) > MAX_DIFF_LINES:
            half = MAX_DIFF_LINES // 2
            head = lines[:half]
            tail = lines[-half:]
            lines = head + [f"... [diff truncated (exceeded {MAX_DIFF_LINES} lines)] ..."] + tail
        diff_str = "\n".join(lines)
        if len(diff_str.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
            diff_str = diff_str[:MAX_DIFF_BYTES - 100] + f"\n... [diff truncated (exceeded {MAX_DIFF_BYTES} bytes)] ..."
        return diff_str, additions, deletions

    def _write(
        self,
        path: Path,
        content: str,
    ) -> ToolResult:

        old_content = ""
        if path.exists() and path.is_file():
            try:
                old_content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                old_content = ""

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            str(content),
            encoding="utf-8",
        )

        diff_text, additions, deletions = self._compute_diff(path.name, old_content, str(content))

        return ToolResult(
            success=True,
            stdout=(
                f"Wrote {len(str(content))} characters "
                f"to '{path.name}' (Updated with +{additions} -{deletions})."
            ),
            diff=diff_text,
            metadata={
                "diff": diff_text,
                "additions": additions,
                "deletions": deletions,
                "path": path.name,
            },
        )

    # ------------------------------------------------------------------

    def _append(
        self,
        path: Path,
        content: str,
    ) -> ToolResult:

        if not path.exists():

            return ToolResult(
                success=False,
                stderr="File does not exist.",
            )

        old_content = path.read_text(encoding="utf-8", errors="replace")
        new_content = old_content + str(content)

        with path.open(
            "a",
            encoding="utf-8",
        ) as fp:

            fp.write(str(content))

        diff_text, additions, deletions = self._compute_diff(path.name, old_content, new_content)

        return ToolResult(
            success=True,
            stdout=(
                f"Appended {len(str(content))} characters "
                f"to '{path.name}' (Updated with +{additions} -{deletions})."
            ),
            diff=diff_text,
            metadata={
                "diff": diff_text,
                "additions": additions,
                "deletions": deletions,
                "path": path.name,
            },
        )

    # ------------------------------------------------------------------

    def _replace(
        self,
        path: Path,
        old_text: str | None,
        new_text: str | None,
        count: int = 1,
        replace_all: bool = False,
    ) -> ToolResult:
        """
        Replace occurrences of old_text with new_text.
        Supports optional count (default 1) or replace_all (if all=True).
        """

        if not path.exists():
            return ToolResult(
                success=False,
                stderr="File does not exist.",
            )

        if not path.is_file():
            return ToolResult(
                success=False,
                stderr="Target is not a file.",
            )

        if not isinstance(old_text, str) or not old_text:
            return ToolResult(
                success=False,
                stderr="Argument 'old_text' is required and cannot be empty.",
            )

        if new_text is None:
            new_text = ""

        if not isinstance(new_text, str):
            new_text = str(new_text)

        content = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if old_text not in content:
            return ToolResult(
                success=False,
                stderr="Target text was not found in file.",
            )

        if replace_all:
            updated = content.replace(old_text, new_text)
            occurrences = content.count(old_text)
        else:
            try:
                count = int(count)
                if count < 1:
                    count = 1
            except (TypeError, ValueError):
                count = 1
            updated = content.replace(old_text, new_text, count)
            occurrences = min(content.count(old_text), count)

        path.write_text(
            updated,
            encoding="utf-8",
        )

        diff_text, additions, deletions = self._compute_diff(path.name, content, updated)

        return ToolResult(
            success=True,
            stdout=(
                f"Successfully replaced {occurrences} occurrence(s) of text in '{path.name}' "
                f"(Updated with +{additions} -{deletions})."
            ),
            diff=diff_text,
            metadata={
                "diff": diff_text,
                "additions": additions,
                "deletions": deletions,
                "path": path.name,
            },
        )
