from __future__ import annotations

import difflib
import os
import errno
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from typing import Any, Final

from tools.base import BaseTool
from tools.models import ToolResult
from core.sanitize import sanitize
from core.kernel.events import bus
from core.accept_edits_state import (
    PendingEdit,
    _accept_edits_pending,
    _accept_edits_enabled,
    _compute_digest,
    _highlight_word_changes,
)


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

        # ── Phase 2.A: Command-shaped path detection ───────────────────────
        # When the model routes a bare shell command (no file extension, no
        # path separators) to file_system for a path that does NOT exist
        # anywhere in the workspace, fail with a typed error instead of
        # attempting to read a nonexistent file. This catches inputs like
        # 'pwd', 'ls', 'git status' mistakenly sent to file_system, while
        # still allowing reading/writing real files that happen to have no
        # extension (e.g. 'Makefile', 'README').
        if action in ("read", "edit", "write", "append", "replace"):
            _path_stripped = path.strip()
            # Check if the path resolves to an existing file or directory
            # in the workspace. If it exists, it's a valid path, not a command.
            try:
                _resolved = (self.workspace / _path_stripped).resolve()
                _exists = _resolved.exists()
            except Exception:
                _exists = False
            if not _exists:
                # A command-shaped path has NO file extension and NO path
                # separators. Commands with spaces are also detected.
                _has_extension = ("." in _path_stripped and not _path_stripped.startswith("."))
                _has_separator = "/" in _path_stripped or "\\" in _path_stripped
                _is_multi_token = " " in _path_stripped
                _looks_like_command = (
                    (not _has_extension and not _has_separator and not _path_stripped.startswith("."))
                    or (_is_multi_token and not _has_extension and not _has_separator)
                )
                if _looks_like_command:
                    return ToolResult(
                        success=False,
                        stderr=(
                            f"[WRONG_TOOL] The input '{path}' appears to be a shell "
                            f"command, not a file path. Use execute_shell with "
                            f'{{"command": "{path}"}} instead of file_system.'
                        ),
                        returncode=-1,
                        status="wrong_tool",
                        metadata={
                            "wrong_tool": True,
                            "suggested_tool": "execute_shell",
                            "suggested_args": {"command": path},
                        },
                    )

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

            target = self._resolve_workspace_path(path)

            if action is FileAction.LIST:
                return self._list(target, recursive=bool(kwargs.get("recursive", False)))

            if action is FileAction.READ:
                bus.emit("file_read", {"path": path, "action": "read"})
                return self._read(target)

            if action is FileAction.READ_MANY:
                return self._handle_read_many(kwargs)

            if action is FileAction.EDIT:
                bus.emit("file_modified", {"path": path, "action": "edit"})
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
                bus.emit("file_written", {"path": path, "action": "write"})
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

    def _resolve_workspace_path(self, relative_path: str) -> Path:
        """
        Resolve a path safely inside the workspace using Path.resolve() + relative_to() to prevent path traversal.
        Rejects absolute paths, .. components, and symlink escapes.
        Implements parent-directory TOCTOU protection using dir_fd + O_DIRECTORY + O_NOFOLLOW traversal.
        """
        import os
        import errno

        # Convert to Path and check for dangerous components before resolving
        path_obj = Path(relative_path)

        # Check if the path is absolute
        if path_obj.is_absolute():
            raise PermissionError("Absolute paths are forbidden.")

        # Convert to string and check manually for '..' components to prevent traversal
        path_parts = str(relative_path).split('/')
        if '..' in path_parts:
            raise PermissionError("Path traversal with '..' is forbidden.")

        # Split the path into directory components and file component
        # For path like 'dir1/dir2/file.txt', we'll have ['dir1', 'dir2'] as dirs and 'file.txt' as file
        full_path = Path(relative_path)
        *dir_parts, file_part = full_path.parts if full_path.parts else [""]

        # If there are directory components, perform secure traversal on them
        if dir_parts:
            # Start from the workspace directory descriptor
            workspace_fd = os.open(str(self.workspace), os.O_RDONLY | os.O_DIRECTORY)
            try:
                current_fd = workspace_fd
                for i, dir_component in enumerate(dir_parts):
                    if dir_component == ".." or dir_component == ".":
                        raise PermissionError("Path traversal with '..' or '.' in parts is forbidden.")

                    # Open each directory component with O_NOFOLLOW to prevent symlink attacks during traversal
                    try:
                        next_fd = os.open(dir_component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current_fd)
                        # Successfully opened as directory, continue traversal
                        os.close(current_fd)
                        current_fd = next_fd
                    except OSError as e:
                        # If it's not a directory, that's an error
                        if e.errno == errno.ENOTDIR:
                            raise PermissionError(f"Path component '{dir_component}' is not a directory")
                        else:
                            # For other errors (like ENOENT), re-raise them
                            raise

                # At this point, current_fd refers to the parent directory of the target file
                # Now verify that the final file path doesn't escape the workspace by resolving it completely
                target = (self.workspace / relative_path).resolve()

                # Ensure the resolved path is within the workspace using relative_to
                try:
                    target.relative_to(self.workspace)
                except ValueError:
                    raise PermissionError(
                        "Access outside the workspace is forbidden."
                    )

                return target
            finally:
                os.close(current_fd)
        else:
            # No directory components, just a file in the workspace root
            target = (self.workspace / relative_path).resolve()

            # Ensure the resolved path is within the workspace using relative_to
            try:
                target.relative_to(self.workspace)
            except ValueError:
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
        """Single-file read, returning a ToolResult.

        PATCH-R4.4: Includes ``workspace_relative_path`` in metadata for
        trusted target verification. The path is resolved by the tool itself
        (not from LLM arguments), so it is the authoritative source of truth.
        """
        try:
            content = self._read_raw(path)
            # Compute workspace-relative path for trusted evidence metadata.
            try:
                _rel = str(path.relative_to(self.workspace))
            except (ValueError, AttributeError):
                _rel = path.name
            return ToolResult(
                success=True,
                stdout=content,
                metadata={"workspace_relative_path": _rel},
            )
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
                    target = self._resolve_workspace_path(fp)
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

        # PATCH-R4.5: Batch read isolation — action="read_many", path="".
        # The `_check_required_target_in_evidence` gate requires action in
        # {"read", "view"}, so "read_many" inherently fails to satisfy the target
        # gate. This is the intended fail-closed behavior.
        # NOTE: ToolResult does NOT accept a `summary` keyword argument.
        # The summary string is embedded in stdout via header lines above.
        return ToolResult(
            success=n_ok > 0,
            stdout=combined,
            metadata={"action": "read_many"},
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
        except PermissionError:
            return ToolResult(
                success=False,
                stderr="PATH_CONTAINMENT_REJECTED: Access denied due to path containment policy.",
                returncode=-1,
                status="path_containment_rejected",
            )

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
                expected_original_digest=_compute_digest(old_content) if old_content else "",
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

        # Normal path: write immediately using secure file operations
        # Create parent directories using secure mkdir
        parent_dir = target.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        # Use secure file writing with O_CREAT | O_EXCL to prevent race conditions
        parent_fd = os.open(str(parent_dir), os.O_RDONLY)
        try:
            basename = target.name
            # Try to create the file exclusively
            try:
                fd = os.open(basename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                # File exists, open for writing (but still with O_NOFOLLOW)
                fd = os.open(basename, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
                created = False

            try:
                # Write the content
                os.write(fd, new_content.encode('utf-8'))
            except Exception as e:
                # If there was an error and we just created the file, remove it
                if created:
                    try:
                        os.unlink(basename, dir_fd=parent_fd)
                    except:
                        pass  # Best effort cleanup
                raise
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

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

        # Create parent directories using secure mkdir
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Use secure file writing with O_CREAT | O_EXCL to prevent race conditions
        parent_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            basename = path.name
            # Try to create the file exclusively
            try:
                fd = os.open(basename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                # File exists, open for writing (but still with O_NOFOLLOW)
                fd = os.open(basename, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
                created = False

            try:
                # Write the content
                os.write(fd, str(content).encode('utf-8'))
            except Exception as e:
                # If there was an error and we just created the file, remove it
                if created:
                    try:
                        os.unlink(basename, dir_fd=parent_fd)
                    except:
                        pass  # Best effort cleanup
                raise
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

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

        # Use secure file appending with O_APPEND to prevent race conditions
        parent_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            basename = path.name
            # Open file for appending with O_NOFOLLOW to prevent symlink attacks
            fd = os.open(basename, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                # Append the content
                os.write(fd, str(content).encode('utf-8'))
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

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

        # Use secure file writing with O_CREAT | O_TRUNC to prevent race conditions
        parent_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            basename = path.name
            # Open file for writing with O_NOFOLLOW to prevent symlink attacks
            # Use O_CREAT in case we're creating a new file, O_TRUNC to overwrite
            fd = os.open(basename, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                # Write the updated content
                os.write(fd, updated.encode('utf-8'))
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

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

