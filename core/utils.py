from __future__ import annotations

import shlex
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.security import split_pipe_segments, validate
from core.sanitize import sanitize


# ---------------------------------------------------------------------------
# 1. Validation & Tokenisation  (CC ~ 4)
# ---------------------------------------------------------------------------

def _validate_and_tokenize(cmd_str: str) -> Tuple[bool, str, Optional[List[str]]]:
    """Validate security policy and tokenize *cmd_str*.

    Returns (*ok*, *error*, *tokens*):
        ``(True, "", tokens)`` on success,
        ``(False, "reason", None)`` on failure.
    """
    if not cmd_str:
        return False, "Empty command.", None

    ok, err = validate(cmd_str)
    if not ok:
        return False, f"Security validation failed: {err}", None

    try:
        tokens = shlex.split(cmd_str)
    except Exception as e:
        return False, f"Command tokenization error: {e}", None

    if not tokens:
        return False, "Command parsing resulted in empty arguments.", None

    return True, "", tokens


# ---------------------------------------------------------------------------
# 2. Background process  (CC ~ 4)
# ---------------------------------------------------------------------------

def _handle_background(cmd_str: str) -> Tuple[int, str, str]:
    """Start a background process (``command &``).

    Strips trailing ``&`` (and optional ``> /dev/null`` redirections),
    then launches via ``subprocess.Popen`` with ``start_new_session`` so
    the agent loop is never blocked.
    """
    bg_cmd = cmd_str[:-1].strip() if cmd_str.endswith("&") else cmd_str
    for redir in ["> /dev/null 2>&1", ">/dev/null 2>&1", "> /dev/null", ">/dev/null"]:
        if bg_cmd.endswith(redir):
            bg_cmd = bg_cmd[: -len(redir)].strip()
    try:
        args = shlex.split(bg_cmd)
        if not args:
            return -1, "", "Empty background command."
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return 0, f"Background server process started successfully (PID: {proc.pid}).", ""
    except Exception as e:
        return -1, "", f"Failed to start background process: {e}"


# ---------------------------------------------------------------------------
# 3. Piped command execution  (CC ~ 7)
# ---------------------------------------------------------------------------

def _drain_stderr_into(idx: int, pipe, parts: List[List[str]]) -> None:
    """Read all lines from *pipe* into ``parts[idx]`` (background thread target)."""
    try:
        for line in pipe:
            parts[idx].append(line)
    except ValueError:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def _handle_piped(segments: List[List[str]], timeout: int) -> Tuple[int, str, str]:
    """Execute a pipeline of commands connected via ``|``.

    Spawns every segment as a ``subprocess.Popen``, chains stdout→stdin,
    drains stderr concurrently on daemon threads to prevent deadlock,
    then kills any hung intermediate processes.
    """
    procs: List[subprocess.Popen] = []
    prev_stdout = None
    stderr_parts: List[List[str]] = [[] for _ in segments]
    stderr_threads: List[threading.Thread] = []

    for i, seg_tokens in enumerate(segments):
        proc = subprocess.Popen(
            seg_tokens,
            stdin=prev_stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if prev_stdout is not None:
            prev_stdout.close()
        prev_stdout = proc.stdout
        procs.append(proc)
        t = threading.Thread(
            target=_drain_stderr_into, args=(i, proc.stderr, stderr_parts), daemon=True
        )
        t.start()
        stderr_threads.append(t)

    last_proc = procs[-1]
    stdout_data, stderr_data = last_proc.communicate(timeout=timeout)

    for t in stderr_threads:
        t.join(timeout=5)

    for p in procs[:-1]:
        p.poll()
        if p.returncode is None:
            p.kill()
            p.wait()

    combined_stderr = "".join("".join(part) for part in stderr_parts)
    return (last_proc.returncode or 0), sanitize(stdout_data or ""), sanitize(combined_stderr or "")


# ---------------------------------------------------------------------------
# 4. Simple (non-piped, non-bg) command  (CC ~ 2)
# ---------------------------------------------------------------------------

def _handle_simple(args: List[str], timeout: int) -> Tuple[int, str, str]:
    """Run a single command via ``subprocess.run``."""
    result = subprocess.run(
        args,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, sanitize(result.stdout or ""), sanitize(result.stderr or "")


# ---------------------------------------------------------------------------
# 🎯 Orchestrator  (CC ~ 5)
# ---------------------------------------------------------------------------

def safe_execute_command(command: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Execute a shell command securely without ``shell=True``.

    Supports:
    *   Simple commands (``ls -la``)
    *   Pipelines (``grep foo | wc -l``)
    *   Background processes (``python server.py &``)

    Returns ``(returncode, stdout, stderr)`` — **unchanged** from the legacy
    signature so all callers (``ShellTool``, ``CommandExecutorProtocol``,
    tests) continue to work without modification.

    All exceptions (``TimeoutExpired``, ``OSError``, etc.) are caught
    and returned as structured error tuples — the orchstrator NEVER
    propagates an unhandled exception to the caller.
    """
    cmd_str = command.strip()
    if not cmd_str:
        return -1, "", "Empty command."

    try:
        # 1. Validate + tokenize
        ok, err, tokens_or_none = _validate_and_tokenize(cmd_str)
        if not ok:
            return -1, "", err
        assert tokens_or_none is not None, "validation passed but tokens is None"
        tokens: List[str] = tokens_or_none

        # 2. Background mode?
        is_bg = cmd_str.rstrip().endswith("&")
        if is_bg:
            return _handle_background(cmd_str)

        # 3. Check for pipes
        try:
            ok_p, segments, parse_err = split_pipe_segments(cmd_str)
            if ok_p and len(segments) > 1:
                return _handle_piped(segments, timeout)
        except Exception:
            pass  # fall through to simple command

        # 4. Default: simple command
        return _handle_simple(tokens, timeout)

    except subprocess.TimeoutExpired:
        return -1, "", f"Command execution timed out after {timeout} seconds."
    except Exception as e:
        return -1, "", f"Execution failure: {type(e).__name__}: {str(e)}"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def truncate(text: str, max_len: int = 2000) -> str:
    """Truncate *text* to *max_len* characters, appending a truncation marker."""
    if not text or len(text) <= max_len:
        return text
    return text[:max_len] + f"\n... [Truncated to {max_len} characters]"


def safe_strip(value: Any, default: str = "") -> str:
    """Safely convert value to string and strip whitespace."""
    if value is None:
        return default
    text = str(value)
    return text.strip()
