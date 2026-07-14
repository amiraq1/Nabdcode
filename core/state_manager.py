from __future__ import annotations

import json
import time
from pathlib import Path
from threading import RLock
from typing import Any

STATE_FILE = Path("core/state/shared_state.json")


_FILE_LOCKS: dict[str, RLock] = {}
_MAP_LOCK = RLock()


def _get_file_lock(path: Path) -> RLock:
    key = str(path.resolve())
    with _MAP_LOCK:
        if key not in _FILE_LOCKS:
            _FILE_LOCKS[key] = RLock()
        return _FILE_LOCKS[key]


class SharedStateManager:
    """Atomic shared state manager for multi-agent parallel execution."""

    def __init__(self, state_path: Path | str = STATE_FILE):
        self.state_file = Path(state_path)
        self.lock = _get_file_lock(self.state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._write({"goal": "", "tasks": [], "shared_evidence": [], "log": []})

    def _read(self) -> dict[str, Any]:
        with self.lock:
            if not self.state_file.exists():
                return {"goal": "", "tasks": [], "shared_evidence": [], "log": []}
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {"goal": "", "tasks": [], "shared_evidence": [], "log": []}

    def _write(self, data: dict[str, Any]) -> None:
        with self.lock:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.state_file)

    def add_evidence(self, task_id: str, evidence: str) -> None:
        with self.lock:
            state = self._read()
            if "shared_evidence" not in state:
                state["shared_evidence"] = []
            if "log" not in state:
                state["log"] = []
            state["shared_evidence"].append(f"[{task_id}] {evidence[:500]}")
            state["log"].append(f"{time.time()} - {task_id} done")
            self._write(state)

    def get_shared_context(self) -> str:
        with self.lock:
            state = self._read()
            evidence_list = state.get("shared_evidence", [])
            return "\n".join(evidence_list[-6:])

    def update_task_status(self, task_id: str, status: str) -> None:
        with self.lock:
            state = self._read()
            for t in state.get("tasks", []):
                if t.get("id") == task_id:
                    t["status"] = status
            self._write(state)
