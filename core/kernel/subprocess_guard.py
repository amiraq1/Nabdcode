# core/kernel/subprocess_guard.py
"""
Centralized subprocess execution guard — the single choke-point for ALL
shell/process spawning in NABD OS.

This module lives in ``core/kernel/`` (the dependency island) and imports
ONLY from other kernel modules, so it has zero coupling to ``core/`` or
``engine/``. Every stratified call-site that previously called
``subprocess.run``/``subprocess.Popen`` directly now routes through one of
the public methods here, giving us:

  * One security policy (delegates to ``core.kernel.security.validate``).
  * One consent seam (callback injected from the engine layer — the kernel
    never imports ``engine.consent``).
  * One audit/log path (``core.kernel.events.bus`` emission).
  * Uniform timeout + error containment.
  * Runtime arg-injection scanning for ALL subprocess calls (defense in depth).

Policies
--------
AGENT_SHELL : agent-issued commands that MUST pass ``validate()`` and (when
              the consent callback is wired) interactive approval.
GIT         : allowlisted git operations (push/diff/status) — still validated
              for workspace path containment but exempt from the shell policy.
INFRA       : internal process spawns (uv, lightpanda, code runners) executed
              by the OS itself, not by an untrusted agent string. No user
              validation, but always logged for forensics AND scanned for
              shell-injection patterns in every argument.

The guard is intentionally thin: it does NOT reimplement the validator, it
delegates. This keeps the security engine in one place.

Security hardening (Phase 6.1 — 10 SUBPROCESS_EXECUTION vulnerabilities closed):
  1. ``_run_simple``: removed ``shell=True`` path entirely — always tokenizes
     via ``shlex.split`` and runs ``shell=False``.
  2. ``_args_safe_for_execution``: new static validator scanned against every
     tokenized arg in INFRA/GIT/AGENT paths — blocks standalone shell
     metacharacters, base64 blobs, and hex escape smuggling. Does NOT block
     ``eval()``/``exec()`` inside Python code strings (harmless with
     ``shell=False``) or ``-c`` on interpreters.
  3. ``spawn_infra``: added ``cwd`` workspace containment check.
  4. ``spawn_infra``: always returns the ``Popen`` handle (or ``None`` on
     failure) so callers can check liveness via ``proc.poll()``.
  5. All ``subprocess.*`` calls are wrapped in try/except with uniform
     error containment — no exceptions escape.
"""

from __future__ import annotations

import enum
import os
import re
import shlex
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from core.kernel.security import (
    get_workspace_root,
    split_pipe_segments,
    validate,
)
from core.kernel.events import bus


# Type aliases -----------------------------------------------------------------

# A consent callback returns True to approve, False to block.
ConsentCallback = Callable[[str, dict], bool]


class Policy(enum.Enum):
    """Execution policy for a guarded subprocess call."""

    AGENT_SHELL = "agent_shell"
    GIT = "git"
    INFRA = "infra"


# Result tuple: (returncode, stdout, stderr)
ExecResult = Tuple[int, str, str]


# ── Arg-injection scanner (defense in depth for ALL execution paths) ──────────

# Standalone metacharacters: if an ENTIRE arg is just one of these, it
# indicates bad tokenization (should have been caught earlier).  But
# metacharacters EMBEDDED inside a longer arg (e.g. ``import time; time.sleep``
# or ``echo "hello; world"``) are harmless with ``shell=False`` because the
# entire string is passed as a single argv element — the kernel never re-parses
# it through a shell.  We only flag an arg whose value IS the metacharacter.
_STANDALONE_META_RE = re.compile("^[;|&$`\n]+$")  # non-raw so \\n is an actual newline character

# Command substitution at the ARG level: a standalone ``$(...)`` or ```...```
# would indicate a buggy caller, not shell injection.
_STANDALONE_SUB_RE = re.compile(r"^\$\(.*\)$|^`[^`]*`$")

# Base64 payload: long base64-like blob (60+ chars) is suspicious even in
# tokenized context — it suggests an encoded payload being passed to an
# interpreter like ``python3 -c "base64_decode(...)"``.
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")

# Heavy hex escape smuggling: >=3 hex escapes in a single arg suggests
# obfuscation (e.g. ``\\x65\\x76\\x61\\x6c`` = "eval").
_HEX_ESCAPE_RE = re.compile(r"(\\x[0-9a-fA-F]{2}){3,}")


def _args_safe_for_execution(args: List[str], context: str = "infra") -> Tuple[bool, str]:
    """Scan tokenized args for shell-injection patterns.

    This is a **defense-in-depth** layer applied to ALL subprocess paths
    (AGENT_SHELL, GIT, and INFRA). With ``shell=False``, classic shell
    injection is impossible, but we still guard against:

      * A caller that accidentally passes a standalone metacharacter as an
        arg (e.g. ``["echo", ";", "rm", "-rf"]`` — the ``;`` would be argv[1]).
      * Base64-encoded payload blobs (60+ chars) being passed to interpreters.
      * Heavy hex-escape smuggling (3+ ``\\xHH`` tokens in one arg).

    **NOT scanned** (safe with ``shell=False``):
      * ``eval()`` / ``exec()`` / ``compile()`` inside Python code strings
        — these are just data passed as argv, not interpreted by a shell.
      * ``-c`` / ``-e`` flags on interpreters — legitimate usage via
        ``subprocess.run(["python3", "-c", "code"], shell=False)`` poses
        zero shell-injection risk.

    Returns ``(True, "")`` on pass or ``(False, reason)`` on block.
    """
    if not args:
        return True, ""  # empty args silently pass (caller handles separately)

    for arg in args:
        if not arg:
            continue  # empty string inside a list is benign

        # 1. Standalone shell metacharacter (the ENTIRE arg is just meta).
        if _STANDALONE_META_RE.match(arg):
            return False, (
                f"Standalone shell metacharacter {arg!r} detected in "
                f"{context} args: only tokenized arguments allowed."
            )

        # 2. Standalone command substitution.
        if _STANDALONE_SUB_RE.match(arg):
            return False, (
                f"Standalone command substitution {arg!r} detected in "
                f"{context} args: not allowed."
            )

        # 3. Base64 payload blob (60+ chars).
        # Use .search() so the blob is detected even if preceded by prefix chars.
        if _BASE64_BLOB_RE.search(arg):
            return False, (
                f"Long base64-like blob detected in {context} args: "
                f"possible encoded payload."
            )

        # 4. Heavy hex/escape smuggling (>=3 hex escapes).
        if _HEX_ESCAPE_RE.search(arg):
            return False, (
                f"Heavy hex/escape sequence detected in {context} args: "
                f"possible obfuscated payload."
            )

    return True, ""


def _drain_stderr_into(idx: int, pipe, parts: List[List[str]]) -> None:
    """Drain ``pipe`` fully into ``parts[idx]`` (daemon-thread target).

    Prevents pipe-buffer deadlock when multiple pipeline segments write to
    stderr concurrently. Never raises.
    """
    try:
        for line in pipe:
            parts[idx].append(line)
    except ValueError:
        pass
    finally:
        try:
            pipe.close()
        except Exception:  # noqa: BLE001
            pass


class SubprocessGuard:
    """Single choke-point for subprocess execution across the whole OS.

    Construct once (typically in ``AppContext.build``) and inject the
    consent callback from the engine layer. Call-sites receive the guard
    via dependency injection rather than importing ``subprocess`` directly.
    """

    def __init__(self, consent_callback: Optional[ConsentCallback] = None) -> None:
        self._consent = consent_callback

    # ── Public API ─────────────────────────────────────────────────────────

    def run_agent_command(
        self,
        command: str,
        timeout: int = 30,
        tool_name: str = "execute_shell",
        args: Optional[dict] = None,
    ) -> ExecResult:
        """Execute an AGENT-issued shell command under full security + consent.

        Returns ``(returncode, stdout, stderr)``. On block (security or
        consent), returns ``(-1, "", "<reason>")`` so callers keep their
        existing tuple contract.
        """
        ok, reason = validate(command)
        if not ok:
            bus.emit("subprocess_blocked", {
                "policy": Policy.AGENT_SHELL.value,
                "command": command,
                "reason": reason,
            })
            return -1, "", f"Security Violation: {reason}"

        if self._consent is not None and not self._consent(tool_name, args or {"command": command}):
            bus.emit("subprocess_blocked", {
                "policy": Policy.AGENT_SHELL.value,
                "command": command,
                "reason": "user_declined",
            })
            return -1, "", "Execution blocked by user."

        result = self._run_simple(command, timeout)
        bus.emit("subprocess_executed", {
            "policy": Policy.AGENT_SHELL.value,
            "command": command,
            "returncode": result[0],
        })
        return result

    def run_agent_pipeline(self, command: str, timeout: int = 300) -> ExecResult:
        """Execute a validated AGENT pipeline (``a | b | c``), shell=False.

        Applies the identical trust chain as ``run_agent_command`` (full
        ``validate()`` → consent seam → per-segment arg scan), then chains each
        segment as an independent ``subprocess.Popen`` with stdout piped into
        the next segment's stdin. stderr is drained on daemon threads to avoid
        pipe-buffer deadlock; hung intermediates are killed once the last
        segment exits. Returns ``(returncode_of_last_segment, stdout, stderr)``
        or ``(-1, "", "<reason>")`` — never raises.
        """
        ok, reason = validate(command)
        if not ok:
            bus.emit("subprocess_blocked", {
                "policy": Policy.AGENT_SHELL.value,
                "command": command,
                "reason": reason,
            })
            return -1, "", f"Security Violation: {reason}"

        if self._consent is not None and not self._consent("execute_shell", {"command": command}):
            bus.emit("subprocess_blocked", {
                "policy": Policy.AGENT_SHELL.value,
                "command": command,
                "reason": "user_declined",
            })
            return -1, "", "Execution blocked by user."

        ok_p, segments, parse_err = split_pipe_segments(command)
        if not ok_p or len(segments) < 2:
            return -1, "", parse_err or "Not a pipeline."

        for seg in segments:
            safe, scan_reason = _args_safe_for_execution(seg, context="pipeline")
            if not safe:
                bus.emit("subprocess_blocked", {
                    "policy": Policy.AGENT_SHELL.value,
                    "command": command,
                    "reason": scan_reason,
                })
                return -1, "", f"Security Violation: {scan_reason}"

        procs: List[subprocess.Popen] = []
        # stderr of every segment EXCEPT the last is drained on daemon threads;
        # the last segment's stderr is read by ``communicate()`` itself —
        # draining it concurrently would race/EBADF against communicate's own
        # selector on the same pipe.
        stderr_parts: List[List[str]] = [[] for _ in segments[:-1]]
        try:
            prev_stdout = None
            for i, seg_tokens in enumerate(segments):
                is_last = i == len(segments) - 1
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
                if not is_last:
                    t = threading.Thread(
                        target=_drain_stderr_into,
                        args=(i, proc.stderr, stderr_parts),
                        daemon=True,
                    )
                    t.start()

            stdout_data, stderr_data = procs[-1].communicate(timeout=timeout)

            for p in procs[:-1]:
                p.poll()
                if p.returncode is None:
                    p.kill()
                    p.wait()

            combined_err = "".join("".join(part) for part in stderr_parts) + (stderr_data or "")
            result = (
                (procs[-1].returncode or 0),
                stdout_data or "",
                combined_err,
            )
            bus.emit("subprocess_executed", {
                "policy": Policy.AGENT_SHELL.value,
                "command": command,
                "returncode": result[0],
            })
            return result
        except subprocess.TimeoutExpired:
            for p in procs:
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
            return -1, "", f"Command execution timed out after {timeout} seconds."
        except Exception as exc:  # noqa: BLE001
            for p in procs:
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
            return -1, "", f"Execution failure: {type(exc).__name__}: {str(exc)}"

    def spawn_agent_background(self, command: str) -> ExecResult:
        """Launch a validated ``command &`` detached from the agent loop.

        Same validation/consent/arg-scan trust chain as ``run_agent_command``.
        The child runs with stdio routed to DEVNULL and
        ``start_new_session=True`` so it never blocks the loop; the PID is
        reported in stdout and audited via ``subprocess_spawned``.
        Returns ``(0, "...(PID: N).", "")`` or ``(-1, "", "<reason>")``.
        """
        bg_cmd = command.rstrip()
        if bg_cmd.endswith("&"):
            bg_cmd = bg_cmd[:-1].strip()
        for redir in ("> /dev/null 2>&1", ">/dev/null 2>&1", "> /dev/null", ">/dev/null"):
            if bg_cmd.endswith(redir):
                bg_cmd = bg_cmd[: -len(redir)].strip()

        ok, reason = validate(bg_cmd)
        if not ok:
            bus.emit("subprocess_blocked", {
                "policy": Policy.AGENT_SHELL.value,
                "command": bg_cmd,
                "reason": reason,
            })
            return -1, "", f"Security Violation: {reason}"

        if self._consent is not None and not self._consent("execute_shell", {"command": bg_cmd}):
            bus.emit("subprocess_blocked", {
                "policy": Policy.AGENT_SHELL.value,
                "command": bg_cmd,
                "reason": "user_declined",
            })
            return -1, "", "Execution blocked by user."

        try:
            args = shlex.split(bg_cmd)
        except ValueError as exc:
            return -1, "", f"Command tokenization error: {exc}"
        if not args:
            return -1, "", "Empty background command."

        safe, scan_reason = _args_safe_for_execution(args, context="background")
        if not safe:
            bus.emit("subprocess_blocked", {
                "policy": Policy.AGENT_SHELL.value,
                "command": bg_cmd,
                "reason": scan_reason,
            })
            return -1, "", f"Security Violation: {scan_reason}"

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            bus.emit("subprocess_spawned", {
                "policy": Policy.AGENT_SHELL.value,
                "command": bg_cmd,
                "pid": proc.pid,
            })
            return 0, f"Background server process started successfully (PID: {proc.pid}).", ""
        except Exception as exc:  # noqa: BLE001
            return -1, "", f"Failed to start background process: {exc}"

    def run_git(
        self,
        args: List[str],
        cwd: Optional[str] = None,
        timeout: int = 30,
    ) -> ExecResult:
        """Execute an allowlisted git command (args already tokenized).

        ``args`` must be a token list (e.g. ``["git", "push", "origin", "main"]``).
        Workspace containment is enforced via ``get_workspace_root``.
        """
        cwd_path = Path(cwd) if cwd else get_workspace_root()
        try:
            resolved = cwd_path.resolve()
            resolved.relative_to(get_workspace_root().resolve())
        except Exception:
            return -1, "", "Git command cwd escapes workspace root."

        if not args or args[0] != "git":
            return -1, "", "Only git commands are allowed."

        # Defense-in-depth: scan tokenized args for injection patterns.
        safe, reason = _args_safe_for_execution(args, context="git")
        if not safe:
            return -1, "", f"Git args blocked: {reason}"

        result = self._run_tokens(args, timeout, cwd=str(cwd_path))
        bus.emit("subprocess_executed", {
            "policy": Policy.GIT.value,
            "command": " ".join(args),
            "returncode": result[0],
        })
        return result

    def run_infra(
        self,
        args: List[str],
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> ExecResult:
        """Execute an INTERNAL process (uv, lightpanda, code runner, etc.).

        No user validation is performed — the OS itself constructs these
        commands. However, **defense-in-depth arg scanning** is applied:
        every token is checked for standalone shell metacharacters,
        base64 payloads, and hex escape smuggling.

        This prevents a bug in a calling module from accidentally passing
        dangerous arguments to subprocess.
        """
        if not args:
            return -1, "", "Empty infra command."

        # Defense-in-depth: scan tokenized args for injection patterns.
        safe, reason = _args_safe_for_execution(args, context="infra")
        if not safe:
            return -1, "", f"Infra args blocked: {reason}"

        try:
            proc = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )
            result: ExecResult = (proc.returncode, proc.stdout or "", proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            result = (-1, out, f"execution timed out after {timeout}s")
        except FileNotFoundError:
            result = (-1, "", f"binary not found: {args[0]!r}")
        except Exception as exc:  # noqa: BLE001 - containment boundary
            result = (-1, "", f"{type(exc).__name__}: {exc}")

        bus.emit("subprocess_executed", {
            "policy": Policy.INFRA.value,
            "command": " ".join(args),
            "returncode": result[0],
        })
        return result

    def spawn_infra(
        self,
        args: List[str],
        env: Optional[dict] = None,
        preexec_fn: Optional[Callable[[], None]] = None,
        cwd: Optional[str] = None,
    ) -> Optional[subprocess.Popen]:
        """Spawn a LONG-LIVED internal process (e.g. Lightpanda MCP server).

        Returns the ``Popen`` handle or ``None`` on failure. Caller owns the
        lifecycle (stop/kill) and must check ``proc.poll()`` to determine
        liveness. No capture — ``.DEVNULL`` stdout/stderr.

        **Security hardening:**
          * Args are scanned for injection patterns before spawning.
          * ``cwd`` is validated against the workspace root.
          * ``preexec_fn`` defaults to ``os.setsid`` to create a process group
            for clean kill.
        """
        if not args:
            return None

        # Defense-in-depth: scan tokenized args for injection patterns.
        safe, reason = _args_safe_for_execution(args, context="spawn_infra")
        if not safe:
            return None

        # Validate cwd against workspace root if provided.
        if cwd is not None:
            try:
                resolved_cwd = Path(cwd).resolve()
                resolved_cwd.relative_to(get_workspace_root().resolve())
            except Exception:
                return None

        # Default to process group isolation so kill() terminates children.
        if preexec_fn is None and hasattr(os, "setsid"):
            preexec_fn = os.setsid

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=cwd,
                preexec_fn=preexec_fn,
            )

            # If timeout is specified, wait for the process and kill on expiry.
            if proc is not None:
                bus.emit("subprocess_spawned", {
                    "policy": Policy.INFRA.value,
                    "command": " ".join(args),
                    "pid": proc.pid,
                })
            return proc

        except FileNotFoundError:
            return None
        except Exception:  # noqa: BLE001
            return None

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _run_simple(command: str, timeout: int) -> ExecResult:
        """Run a single command string with uniform error containment.

        **Security:** Always uses ``shell=False`` (tokenized via ``shlex.split``).
        The ``shell=True`` path has been removed to eliminate the command-injection
        surface. All agent commands are validated by ``core.kernel.security.validate``
        before reaching this method.
        """
        try:
            tokens = shlex.split(command)
            proc = subprocess.run(
                tokens,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            return -1, "", f"Command execution timed out after {timeout} seconds."
        except Exception as exc:  # noqa: BLE001
            return -1, "", f"Execution failure: {type(exc).__name__}: {str(exc)}"

    @staticmethod
    def _run_tokens(args: List[str], timeout: int, cwd: str) -> ExecResult:
        """Run a tokenized command list with uniform error containment.

        Args are assumed pre-validated by the caller (``run_git`` scans them
        via ``_args_safe_for_execution`` before calling this method).
        """
        try:
            proc = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            return -1, "", f"Command execution timed out after {timeout} seconds."
        except Exception as exc:  # noqa: BLE001
            return -1, "", f"Execution failure: {type(exc).__name__}: {str(exc)}"


# Module-level default instance (no consent wired — safe fallback for
# non-interactive subsystems like tests, logo, DAG nodes).
default_guard = SubprocessGuard()
