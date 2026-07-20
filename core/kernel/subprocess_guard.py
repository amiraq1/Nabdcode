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

Policies
--------
AGENT_SHELL : agent-issued commands that MUST pass ``validate()`` and (when
              the consent callback is wired) interactive approval.
GIT         : allowlisted git operations (push/diff/status) — still validated
              for workspace path containment but exempt from the shell policy.
INFRA       : internal process spawns (uv, lightpanda, code runners) executed
              by the OS itself, not by an untrusted agent string. No user
              validation, but always logged for forensics.

The guard is intentionally thin: it does NOT reimplement the validator, it
delegates. This keeps the security engine in one place.
"""

from __future__ import annotations

import enum
import subprocess
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from core.kernel.security import (
    get_workspace_root,
    is_safe_command,
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

        result = self._run_simple(command, timeout, shell=False)
        bus.emit("subprocess_executed", {
            "policy": Policy.AGENT_SHELL.value,
            "command": command,
            "returncode": result[0],
        })
        return result

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
        commands. They are still logged for forensics.
        """
        if not args:
            return -1, "", "Empty infra command."
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
    ) -> Optional[subprocess.Popen]:
        """Spawn a LONG-LIVED internal process (e.g. Lightpanda MCP server).

        Returns the ``Popen`` handle or ``None`` on failure. Caller owns the
        lifecycle (stop/kill). No capture — ``.DEVNULL`` stdout/stderr.
        """
        if not args:
            return None
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                preexec_fn=preexec_fn,
            )
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
    def _run_simple(command: str, timeout: int, shell: bool) -> ExecResult:
        """Run a single command string with uniform error containment."""
        try:
            if shell:
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            else:
                import shlex
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
        """Run a tokenized command list with uniform error containment."""
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
