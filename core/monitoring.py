from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

LOG_FILE = Path("core/state/agent_log.jsonl")
_LOG_LOCK = RLock()


class EventLogger:
    @staticmethod
    def log(agent: str, event: str, status: str = "info", **kwargs: Any) -> None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "agent": agent,
            "event": event,
            "status": status,
            **kwargs,
        }
        with _LOG_LOCK:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def get_metrics() -> dict[str, Any]:
        with _LOG_LOCK:
            if not LOG_FILE.exists():
                return {"tasks_done": 0, "fails": 0, "tokens": 0, "lines": 0}
            lines = [
                l
                for l in LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
                if l.strip()
            ]
            tasks_done = sum(
                1 for l in lines if '"status": "done"' in l or '"status": "PASS"' in l
            )
            fails = sum(
                1
                for l in lines
                if '"status": "FAIL"' in l or '"status": "error"' in l
            )
            tokens = sum(
                350
                for l in lines
                if '"event": "tool_call"' in l or "tool_call" in l
            )
            return {
                "tasks_done": tasks_done,
                "fails": fails,
                "tokens": tokens,
                "lines": len(lines),
            }
