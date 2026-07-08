from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(slots=False)
class ToolResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    status: str = ""
    diff: str = ""

    def __post_init__(self):
        if not self.status:
            self.status = "success" if self.success else "error"
        if not self.success and self.returncode == 0:
            self.returncode = -1

    @property
    def output(self) -> str:
        return self.stdout or self.stderr

    def __getitem__(self, key: str) -> Any:
        if key == "status":
            return "success" if self.success else "error"
        if key == "output":
            return self.output
        if key == "error":
            return self.stderr
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default
