from __future__ import annotations

import json
import time
from pathlib import Path
from core.monitoring import EventLogger, LOG_FILE


def render() -> None:
    metrics = EventLogger.get_metrics()
    print("\n=== MULTI-AGENT DASHBOARD ===")
    print(
        f"Tasks Done: {metrics['tasks_done']} | Fails: {metrics['fails']} | Est.Tokens: {metrics['tokens']}"
    )
    print(f"Budget: {metrics['lines'] * 2}s / 180s")
    print("-" * 40)
    if LOG_FILE.exists():
        for line in LOG_FILE.read_text(encoding="utf-8").split("\n")[-8:]:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                icon = (
                    "✅"
                    if e["status"] in ("done", "PASS")
                    else "❌"
                    if e["status"] in ("FAIL", "error")
                    else "⚙️"
                )
                print(
                    f"{icon} [{e.get('ts', '')}] {e.get('agent', ''):15} -> {e.get('event', '')} {e.get('status', '')}"
                )
            except Exception:
                pass


if __name__ == "__main__":
    while True:
        render()
        time.sleep(1.5)
