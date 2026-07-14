from abc import ABC, abstractmethod

from tools.models import ToolResult


class BaseTool(ABC):
    """
    Standard interface that all tools must implement.
    Guarantees all tools communicate with the engine the same way.
    """
    name: str = "unnamed_tool"
    description: str = "No description provided."

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        Primary function for executing the tool.

        Must return a ``tools.models.ToolResult`` with ``success``,
        ``stdout``/``stderr``, and ``returncode`` set. The ``ToolResult``
        dataclass also exposes ``output`` (stdout or stderr), ``status``,
        ``diff``, and ``get()``/``__getitem__`` dict-compat shims so legacy
        dict-style access keeps working.
        """
        pass

    def get_schema(self) -> dict:
        """Return the tool schema for upstream LLM consumption."""
        return {
            "name": self.name,
            "description": self.description
        }
