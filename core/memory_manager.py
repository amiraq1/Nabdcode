"""Persistent memory for NABD OS (Stage 3).

Thread-safe store of session context, learned lessons, and failure logs,
persisted to agent_memory.json. All mutating methods are guarded so a
storage fault can never destabilize the host process.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List

_DEFAULT_PATH = "agent_memory.json"

_EMPTY_SCHEMA: Dict[str, Any] = {
    "short_term_context": "",
    "lessons_learned": [],
    "failure_logs": [],
}


class PersistentMemory:
    """Json-backed, thread-safe persistent memory for the agent."""

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # Normalize to the supported schema, preserving known keys.
            return {
                "short_term_context": data.get("short_term_context", ""),
                "lessons_learned": list(data.get("lessons_learned", [])),
                "failure_logs": list(data.get("failure_logs", [])),
            }
        except FileNotFoundError:
            return dict(_EMPTY_SCHEMA)
        except Exception:
            # Corrupt/unreadable store: start clean rather than crash.
            return dict(_EMPTY_SCHEMA)

    def _save(self) -> None:
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)
        # Atomic replace so a crash mid-write never corrupts the store.
        import os

        os.replace(tmp, self._path)

    # ── Read accessors ────────────────────────────────────────────────
    @property
    def short_term_context(self) -> str:
        with self._lock:
            return self._data["short_term_context"]

    def set_context(self, context: str) -> None:
        with self._lock:
            self._data["short_term_context"] = context

    @property
    def lessons_learned(self) -> List[str]:
        with self._lock:
            return list(self._data["lessons_learned"])

    @property
    def failure_logs(self) -> List[Dict[str, str]]:
        with self._lock:
            return [dict(entry) for entry in self._data["failure_logs"]]

    # ── Mutators (guarded for stability) ──────────────────────────────
    def add_lesson(self, lesson: str) -> None:
        """Persist an architectural insight or fixed-bug lesson."""
        try:
            with self._lock:
                self._data["lessons_learned"].append(lesson)
                self._save()
        except Exception:
            # Storage failure must not break the agent loop.
            pass

    def log_failure(self, failed_action: str, error: str) -> None:
        """Record a failed strategy so it isn't retried blindly."""
        try:
            with self._lock:
                self._data["failure_logs"].append(
                    {"action": failed_action, "error": error}
                )
                self._save()
        except Exception:
            pass
