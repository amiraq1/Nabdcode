import time
from typing import Dict, Any
from engine.events import bus

class MetricsEngine:
    def __init__(self):
        self.start_time = time.time()
        self.api_calls_count = 0
        self.total_api_duration = 0.0
        self.commands_count = 0
        
        bus.subscribe("tool_completed", self._on_tool_completed)

    def _on_tool_completed(self, payload: dict):
        if payload.get("tool") == "execute_shell":
            self.commands_count += 1

    def record_api_call(self, duration: float = 0.0):
        self.api_calls_count += 1
        self.total_api_duration += duration

    def summary(self) -> Dict[str, Any]:
        uptime = int(time.time() - self.start_time)
        return {
            "uptime_seconds": uptime,
            "commands": {"count": self.commands_count},
            "api_calls": {"count": self.api_calls_count, "total_duration": round(self.total_api_duration, 2)}
        }
