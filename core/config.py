"""Agent runtime configuration.

All values are safe defaults; override with environment variables or a `.env`
file. No secrets should be added here — use `NVIDIA_API_KEY` in `.env` instead.
"""

from __future__ import annotations

import getpass
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _resolve_path(env_var: str, default: Path) -> Path:
    """Return a path from the environment or the supplied default."""
    value = os.getenv(env_var)
    if value:
        return Path(value).expanduser().resolve()
    return default


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


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

    max_sessions: int = 50
    max_output: int = 2000
    max_evidence_records: int = 10

    def __post_init__(self) -> None:
        self.max_sessions = _clamp(self.max_sessions, 1, 1000)
        self.max_output = _clamp(self.max_output, 100, 100000)
        self.max_evidence_records = _clamp(self.max_evidence_records, 1, 1000)


# ── Persistent configuration / BYOK key management ──────────────────────────

class ConfigManager:
    """Persistent, file-backed configuration for NABD OS.

    Stores user-supplied secrets (API keys) under a stable per-user config file
    so the CLI can run in a Bring-Your-Own-Key (BYOK) mode without forcing
    environment variables or hardcoded credentials.
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or (Path.home() / ".config" / "nabdcode")
        self.config_path = self.config_dir / "config.json"

    def _load(self) -> dict:
        """Return the parsed config dict, or {} when missing/corrupt."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except Exception:
                # Fail-open: never let a malformed file crash startup.
                pass
        return {}

    def _save(self, data: dict) -> None:
        """Atomically-ish persist config, creating the directory if needed."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        # A user-owned API key file should not be world-readable.
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass

    def get_api_key(self, provider: str = "openrouter") -> str | None:
        """Return a stored key for ``provider`` without prompting, or None."""
        data = self._load()
        keys = data.get("api_keys")
        if isinstance(keys, dict) and keys.get(provider):
            return str(keys[provider])
        # Backwards-compatible flat key (e.g. "openrouter": "...").
        if data.get(provider):
            return str(data[provider])
        return None

    def get_or_prompt_api_key(self, provider: str = "openrouter") -> str:
        """Return the stored key, or interactively prompt, persist, and return it.

        Graceful on empty input: re-prompts (up to 3 attempts) and raises a
        clear error instead of looping or crashing.
        """
        existing = self.get_api_key(provider)
        if existing:
            return existing

        prompt = (
            "🔑 [NABD OS] API Key not found. "
            f"Please enter your {provider} API Key:"
        )
        for _ in range(3):
            entered = getpass.getpass(prompt)
            if entered and entered.strip():
                key = entered.strip()
                data = self._load()
                data.setdefault("api_keys", {})[provider] = key
                self._save(data)
                return key

        raise ValueError(
            f"No API key provided for provider '{provider}'. "
            "Set it via the configuration file or environment variable."
        )
