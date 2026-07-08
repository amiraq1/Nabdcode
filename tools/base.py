from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseTool(ABC):
    """
    Standard interface that all tools must implement.
    Guarantees all tools communicate with the engine the same way.
    """
    name: str = "unnamed_tool"
    description: str = "No description provided."

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Primary function for executing the tool.
        Must return a dict with "status", "output", and optionally "error"."
        """
        pass
        
    def get_schema(self) -> dict:
        """Return the tool schema for upstream LLM consumption."""
        return {
            "name": self.name,
            "description": self.description
        }
