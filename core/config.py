"""Agent runtime configuration.

All values are safe defaults; override with environment variables or a `.env`
file. No secrets should be added here — use `NVIDIA_API_KEY` in `.env` instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _resolve_path(env_var: str, default: Path) -> Path:
    """Return a path from the environment or the supplied default."""
    value = os.getenv(env_var)
    if value:
        return Path(value).expanduser().resolve()
    return default


@dataclass
class AgentConfig:
    """Single source of truth for filesystem and runtime parameters."""

    # Workspace where file_system tool operates. Defaults to the current
    # working directory at import time, then stays pinned.
    workspace_root: Path = field(
        default_factory=lambda: _resolve_path("NABD_WORKSPACE_ROOT", Path.cwd().resolve())
    )

    # Root directory for Nabd runtime data (sessions, logs, memory db).
    # Kept in sync with workspace_root by default.
    root_dir: Path = field(
        default_factory=lambda: _resolve_path("NABD_ROOT_DIR", Path.cwd().resolve())
    )

    session_dir: Path = field(
        default_factory=lambda: _resolve_path(
            "NABD_SESSION_DIR", Path.cwd().resolve() / "sessions"
        )
    )

    log_dir: Path = field(
        default_factory=lambda: _resolve_path(
            "NABD_LOG_DIR", Path.cwd().resolve() / "logs"
        )
    )

    max_sessions: int = int(os.getenv("NABD_MAX_SESSIONS", "50"))
    max_output: int = int(os.getenv("NABD_MAX_OUTPUT", "2000"))
    max_evidence_records: int = int(os.getenv("NABD_MAX_EVIDENCE_RECORDS", "10"))
