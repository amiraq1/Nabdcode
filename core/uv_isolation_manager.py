"""Stage 3 (Lifecycle) — Ephemeral Package Isolation via `uv`.

Runs an arbitrary code payload in a throwaway `uv` virtual environment with
pinned dependencies, so third-party packages can be exercised without
polluting the host interpreter. The temporary script is always removed in a
`finally` block, and every failure mode (missing `uv`, timeout, crash) is
contained into a safe result dict so NABD OS never destabilizes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List


class UvIsolationManager:
    """Executes code in an ephemeral uv-isolated environment."""

    def __init__(self, uv_bin: str = "uv") -> None:
        self.uv_bin = uv_bin

    def _build_command(self, tmp_path: str, dependencies: List[str]) -> List[str]:
        """Construct the uv run command with --with flags per dependency."""
        cmd: List[str] = [self.uv_bin, "run"]
        for dep in dependencies:
            cmd += ["--with", dep]
        cmd.append(tmp_path)
        return cmd

    def run_in_isolated_env(
        self, code_str: str, dependencies: List[str], timeout: float = 10.0
    ) -> Dict[str, Any]:
        """Run ``code_str`` in an isolated uv env with ``dependencies``.

        Returns:
            {"success": bool, "stdout": str, "stderr": str, "exit_code": int}
        On any failure (missing uv, timeout, crash) success is False and the
        error is captured in stderr rather than raised.
        """
        tmp_path = None
        try:
            # 1. Write the payload to a secure temp file (atomic-ish: mkstemp).
            fd, tmp_path = tempfile.mkstemp(prefix="nabd_iso_", suffix=".py")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(code_str)

            # 2. Ensure uv is actually available before spawning.
            if shutil.which(self.uv_bin) is None:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"uv binary not found: {self.uv_bin!r}",
                    "exit_code": -1,
                }

            # 3. Build and run the isolated command.
            cmd = self._build_command(tmp_path, dependencies)
            proc = subprocess.run(  # nosec - verified safe
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode,
            }
        except subprocess.TimeoutExpired as exc:
            # Hard timeout: report failure, leave no orphan confirmed.
            return {
                "success": False,
                "stdout": (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                "stderr": f"execution timed out after {timeout}s",
                "exit_code": -1,
            }
        except Exception as exc:  # noqa: BLE001 - containment boundary
            return {
                "success": False,
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "exit_code": -1,
            }
        finally:
            # 4. Always remove the temp script, even on timeout/crash.
            if tmp_path is not None:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
