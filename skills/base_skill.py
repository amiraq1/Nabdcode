"""Base contract for NABD OS dynamic Skills architecture.

Each skill subclasses BaseSkill and implements execute(). The base run()
wrapper guards execute() in a try/except so a failing skill cannot
destabilize the host process. Skills may optionally receive an
``mcp_context`` registry (read-only access to PersistentMemory + session
status) injected by the adapter layer.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    """Abstract contract every NABD OS skill must satisfy."""

    name: str
    description: str

    def __init__(self, name: str, description: str, mcp_context: Any = None) -> None:
        self.name = name
        self.description = description
        # Bound MCP registry (read-only). May be None (context-blind mode).
        self.mcp_context = mcp_context

    def bind_context(self, mcp_context: Any) -> "BaseSkill":
        """Attach a live MCP context registry; returns self for chaining."""
        self.mcp_context = mcp_context
        return self

    @abstractmethod
    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Skill-specific logic. Subclasses must implement this.

        The adapter layer injects ``mcp_context`` as a keyword argument when
        a live registry is available; skills should treat it as optional.
        """
        raise NotImplementedError

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the skill inside a guard to keep the system stable.

        Catches all exceptions so a single misbehaving skill cannot crash
        the orchestrator; failures are returned as an error payload.
        """
        try:
            # Inject the bound MCP registry if present (context-aware mode).
            if self.mcp_context is not None:
                kwargs.setdefault("mcp_context", self.mcp_context)
            return self.execute(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - containment boundary
            return {"skill": self.name, "error": str(exc), "status": "failed"}
