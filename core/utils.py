from __future__ import annotations

import shlex
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.security import split_pipe_segments, validate
from core.sanitize import sanitize
from core.kernel.subprocess_guard import default_guard


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
    """Start a background process (``command &``) via the centralized SubprocessGuard."""
    return default_guard.spawn_agent_background(cmd_str)


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


def _handle_piped(cmd_str: str, timeout: int) -> Tuple[int, str, str]:
    """Execute a pipeline of commands connected via ``|`` using the centralized SubprocessGuard."""
    return default_guard.run_agent_pipeline(cmd_str, timeout=timeout)


# ---------------------------------------------------------------------------
# 4. Simple (non-piped, non-bg) command  (CC ~ 2)
# ---------------------------------------------------------------------------

def _handle_simple(cmd_str: str, timeout: int) -> Tuple[int, str, str]:
    """Run a single command via the centralized SubprocessGuard (shell=False).

    NBD-04: the ORIGINAL command text is handed to the guard (which re-tokenizes
    deterministically), never a ``" ".join(args)`` reconstruction — that join
    silently destroyed quoted argument boundaries (e.g. a path named
    ``input file.txt`` became two argv elements).
    """
    code, out, err = default_guard.run_agent_command(cmd_str, timeout=timeout)
    return code, sanitize(out), sanitize(err)


# ---------------------------------------------------------------------------
# 🎯 Orchestrator  (CC ~ 5)
# ---------------------------------------------------------------------------

def safe_execute_command(command: str, timeout: int = 300) -> Tuple[int, str, str]:
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

    **Timeout:** Default is 300s (5 minutes) to accommodate full test-suite
    runs on mobile hardware without false timeouts. The previous value of
    120s was insufficient when the full suite (1346 tests) took ~127s.
    When the timeout fires, a TIMEOUT failure is returned with a clear
    message — never a silent hang.
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
                return _handle_piped(cmd_str, timeout)
        except Exception:
            pass  # fall through to simple command

        # 4. Default: simple command — pass the ORIGINAL text (NBD-04), the
        #    guard re-tokenizes identically to ``tokens`` but keeps quoted
        #    boundaries intact. ``tokens`` remains the validated reference.
        return _handle_simple(cmd_str, timeout)

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
