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
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
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

class ToolPreconditionError(Exception):
    """Exception raised when a tool is called before its required preconditions are met."""
    def __init__(self, code: str, safe_message: str, recommended_transition: str):
        self.code = code
        self.safe_message = safe_message
        self.recommended_transition = recommended_transition
        # We format it exactly how the LLM should see it
        super().__init__(f"ToolPreconditionError[{code}]: {safe_message} \\nRecommended Action: {recommended_transition}")

