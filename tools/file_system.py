from __future__ import annotations

import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from tools.base import BaseTool
from tools.models import ToolResult
from core.sanitize import sanitize


# ── Accept-edits queue (shared across turns) ───────────────────────────────
@dataclass
class PendingEdit:
    """A file edit awaiting user approval before being written to disk."""
    path: str            # original relative path (for display)
    resolved_path: str   # absolute path resolved against workspace (for write)
    old_content: str
    new_content: str
    diff: str
    additions: int
    removals: int


# Module-level queue: populated by _handle_edit() when accept-edits mode is
# active, drained by ui/repl_termux.py after each agent turn completes.
_accept_edits_pending: list[PendingEdit] = []
_accept_edits_enabled: bool = False


def _highlight_word_changes(old_line: str, new_line: str) -> tuple[str, str]:
    """Compare two lines at word level and return Rich-markup highlighted versions.

    Uses ``difflib.SequenceMatcher`` to split lines into word tokens and
    colourises changed portions:

    * ``[bold red]...[/bold red]`` for deleted words
    * ``[bold green]...[/bold green]`` for inserted words

    Unchanged words are returned as-is (no markup). The result is safe to pass
    through ``console.print()`` (Rich markup) or ``render_diff()`` (ANSI — the
    tags are passed through as plain text in unchanged lines).
    """
    matcher = difflib.SequenceMatcher(None, old_line.split(), new_line.split())
    old_parts: list[str] = []
    new_parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_words = " ".join(old_line.split()[i1:i2])
        new_words = " ".join(new_line.split()[j1:j2])
        if tag == "equal":
            old_parts.append(old_words)
            new_parts.append(new_words)
        elif tag in ("replace", "delete"):
            old_parts.append(f"[bold red]{old_words}[/bold red]")
            if tag == "replace":
                new_parts.append(f"[bold green]{new_words}[/bold green]")
        elif tag == "insert":
            new_parts.append(f"[bold green]{new_words}[/bold green]")
    return " ".join(old_parts), " ".join(new_parts)


class FileAction(str, Enum):
    READ = "read"
    READ_MANY = "read_many"
    EDIT = "edit"
    WRITE = "write"
    APPEND = "append"
    REPLACE = "replace"
    LIST = "list"


MAX_DIFF_BYTES = 16 * 1024  # 16KB limit (very safe for local context)
MAX_DIFF_LINES = 150  # max lines to show in a prompt

# Maximum characters returned for any single file read. ~3000-4000 tokens,
# protecting local-model context windows from OOM / overflow.
MAX_READ_CHARS = 12000


class FileSystemTool(BaseTool):
    """
    Safe local file system tool.

    Supported actions:
        - read
        - read_many  (parallel batch read — pass 'paths' as list or comma-separated)
        - edit  (write new content with visual diff display)
        - write
        - append
        - replace

    All operations are restricted to the configured workspace.
    """

    name: Final[str] = "file_system"

    description: Final[str] = (
        "Safely read, list, write, edit, append, and replace files inside the workspace. "
        "Required args: 'action' ('read','read_many','edit','list','write','append','replace'), 'path' (str). "
        "Use action='list' to enumerate a directory (pass 'recursive': true to walk subfolders) — "
        "this is the ONLY way to discover files; do NOT use shell ls/find. "
        "For write/append pass 'content'. For replace pass 'old_text','new_text', optional 'count'/'all'. "
        "For parallel batch reads, use action='read_many' with 'paths' (list or comma-separated string). "
        "For visual diff editing, use action='edit' with 'path' and 'content' (the full new file content)."
    )

    MAX_READ_SIZE: Final[int] = 1_000_000  # 1 MB

    def __init__(self, workspace: str | Path = ".", snapshot_engine: Any = None) -> None:
        self.workspace = Path(workspace).resolve()
        # Optional SnapshotEngine for pre-write backups (enables /undo).
        # When None, writes proceed without snapshotting (no behavior change).
        self._snap = snapshot_engine

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
                stderr="Missing required argument 'action'. Allowed values: 'read', 'edit', 'write', 'append', 'replace'.",
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
                    "Allowed values: read, read_many, edit, write, append, replace."
                ),
            )

        try:

            target = self._resolve(path)

            if action is FileAction.LIST:
                return self._list(target, recursive=bool(kwargs.get("recursive", False)))

            if action is FileAction.READ:
                return self._read(target)

            if action is FileAction.READ_MANY:
                return self._handle_read_many(kwargs)

            if action is FileAction.EDIT:
                return self._handle_edit(path, target, kwargs)

            # ── Pre-write snapshot (enables /undo) ───────────────────────
            # Fire-and-forget: a snapshot failure must NEVER block the write.
            if self._snap is not None and action in (
                FileAction.EDIT,
                FileAction.WRITE,
                FileAction.APPEND,
                FileAction.REPLACE,
            ):
                try:
                    self._snap.save(path)
                except Exception:
                    pass

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

    def _read_raw(self, path: Path) -> str:
        """Read file content as a raw string, raising on errors.

        Validates existence, file type, and size. Clamps output to
        MAX_READ_CHARS to protect context windows. Returns sanitized text.
        """
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path.name}")
        if not path.is_file():
            raise IsADirectoryError(f"Target is not a file: {path.name}")
        if path.stat().st_size > self.MAX_READ_SIZE:
            raise ValueError(f"File is too large to read: {path.name}")

        text = path.read_text(encoding="utf-8", errors="replace")

        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + (
                f"\n\n... [TRUNCATED] File exceeds {MAX_READ_CHARS} characters. "
                "This is a partial read to protect AI memory. Use 'execute_shell' "
                "with 'grep', 'head', or 'tail' to inspect specific parts."
            )
        return sanitize(text, preserve_tabs=True, preserve_newlines=True)

    def _read(self, path: Path) -> ToolResult:
        """Single-file read, returning a ToolResult."""
        try:
            content = self._read_raw(path)
            return ToolResult(success=True, stdout=content)
        except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
            return ToolResult(success=False, stderr=str(exc))

    # ------------------------------------------------------------------

    def read_files_parallel(
        self, file_paths: list[str], max_workers: int = 8
    ) -> dict[str, str]:
        """Read multiple files concurrently using a thread pool.

        Args:
            file_paths: List of relative workspace paths to read.
            max_workers: Max parallel threads (capped to len(file_paths)).

        Returns:
            {path: content_or_error} dict. Each value is either the
            sanitized file content or an error message string.
        """
        results: dict[str, str] = {}
        if not file_paths:
            return results

        n_workers = min(max_workers, len(file_paths))
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            future_to_path: dict[Any, str] = {}
            for fp in file_paths:
                try:
                    target = self._resolve(fp)
                    future = executor.submit(self._read_raw, target)
                    future_to_path[future] = fp
                except Exception as exc:
                    results[fp] = f"Error resolving path '{fp}': {exc}"

            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    results[path] = future.result()
                except Exception as exc:
                    results[path] = f"Error reading {path}: {exc}"
        return results

    def _parse_paths(self, raw_paths: Any) -> list[str]:
        """Normalise ``paths`` argument into a list of path strings."""
        if isinstance(raw_paths, list):
            return [str(p) for p in raw_paths]
        if isinstance(raw_paths, str):
            return [p.strip() for p in raw_paths.split(",") if p.strip()]
        return []

    def _handle_read_many(self, kwargs: dict[str, Any]) -> ToolResult:
        """Handle the ``read_many`` action: parallel batch read of multiple files.

        Accepts ``paths`` (list or comma-separated string) and reads all of
        them concurrently via ``read_files_parallel()``. Returns a combined
        ``ToolResult`` with per-file headers and content.
        """
        paths = self._parse_paths(kwargs.get("paths", []))
        if not paths:
            return ToolResult(
                success=False,
                stderr="Missing required argument 'paths' for action 'read_many'. "
                       "Provide a list or comma-separated string of file paths.",
            )

        results = self.read_files_parallel(paths)
        if not results:
            return ToolResult(success=False, stderr="No files were read.")

        lines: list[str] = []
        header_lines: list[str] = []
        for path_str, content in results.items():
            # Calculate line count for the header
            line_count = len(content.splitlines()) if not content.startswith("Error") else 0
            if line_count:
                header_lines.append(f"READ [{path_str}] {line_count} lines")
            else:
                header_lines.append(f"READ [{path_str}]")
            lines.append(f"\n{'─' * 48}")
            lines.append(f"📄 {path_str}")
            lines.append(f"{'─' * 48}")
            lines.append(content)

        combined = "\n".join(header_lines) + "\n" + "\n".join(lines)
        n_ok = sum(1 for v in results.values() if not v.startswith("Error"))
        n_err = len(results) - n_ok
        summary = f"Read {n_ok} file(s)"
        if n_err:
            summary += f" ({n_err} error(s))"

        return ToolResult(
            success=n_ok > 0,
            stdout=combined,
            summary=summary,
        )

    def _handle_edit(self, path_str: str, target: Path, kwargs: dict[str, Any]) -> ToolResult:
        """Handle ``edit`` action: write new content with visual diff display.

        Reads the old content (or empty if new file), computes a unified diff,
        writes the new content, and returns a ``ToolResult`` with the diff
        metadata so ``engine/renderer.py`` can display the colored diff.
        """
        new_content = kwargs.get("content", "")
        if not isinstance(new_content, str) or not new_content:
            return ToolResult(
                success=False,
                stderr="Argument 'content' is required for action 'edit' and cannot be empty.",
            )

        # Read old content (best-effort; new files have no old content).
        try:
            old_content = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            old_content = ""

        # Compute unified diff with 2 lines of context.
        diff_lines = list(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path_str}",
            tofile=f"b/{path_str}",
            n=2,
        ))
        additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removals = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

        # Build compact diff display (max 40 lines).
        diff_display = "".join(diff_lines[:40])
        if len(diff_lines) > 40:
            remainder = len(diff_lines) - 40
            diff_display += f"\n... (+{remainder} more diff lines, use 'read' to inspect full file)"

        # ── Accept-edits gate ────────────────────────────────────────────
        # When accept-edits mode is active, queue the edit for user approval
        # instead of writing to disk immediately. The queue is drained by
        # ui/repl_termux.py after the agent turn completes.
        if _accept_edits_enabled:
            _accept_edits_pending.append(PendingEdit(
                path=path_str,
                resolved_path=str(target),
                old_content=old_content,
                new_content=new_content,
                diff=diff_display,
                additions=additions,
                removals=removals,
            ))
            summary = f"Pending edit: {path_str} (+{additions} -{removals}) — awaiting approval"
            return ToolResult(
                success=True,
                stdout=summary,
                diff=diff_display,
                metadata={
                    "diff": diff_display,
                    "additions": additions,
                    "deletions": removals,
                    "path": path_str,
                    "pending_approval": True,
                },
            )

        # Normal path: write immediately.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")

        summary = f"Updated {path_str} with {additions} additions and {removals} removals"

        return ToolResult(
            success=True,
            stdout=summary,
            diff=diff_display,
            metadata={
                "diff": diff_display,
                "additions": additions,
                "deletions": removals,
                "path": path_str,
            },
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


    def _list(self, path: Path, recursive: bool = False) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, stderr=f"Path not found: {path}")
        if not path.is_dir():
            return ToolResult(success=False, stderr="Target is not a directory. Use action 'read' for files.")
        _SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".nabd", ".cache"}
        lines: list[str] = []
        try:
            seq = sorted(path.rglob("*"), key=lambda x: str(x).lower()) if recursive \
                  else sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for p in seq:
                if any(part in _SKIP for part in p.parts):
                    continue
                rel = p.relative_to(self.workspace) if recursive else p.name
                if p.is_dir():
                    lines.append(f"[DIR]  {rel}/")
                else:
                    try:
                        lines.append(f"[FILE] {rel} ({p.stat().st_size} bytes)")
                    except Exception:
                        lines.append(f"[FILE] {rel}")
                if len(lines) >= 800:
                    lines.append("... [TRUNCATED] too many entries; list subfolders individually.")
                    break
        except Exception as exc:
            return ToolResult(success=False, stderr=f"{type(exc).__name__}: {exc}")
        root = "." if path == self.workspace else str(path.relative_to(self.workspace))
        header = f"Directory listing for '{root}'{' (recursive)' if recursive else ''} — {len(lines)} entries:"
        body = "\n".join(lines) if lines else "(empty directory)"
        return ToolResult(success=True, stdout=sanitize(f"{header}\n{body}", preserve_newlines=True))

