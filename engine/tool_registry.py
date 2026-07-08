from typing import Dict
from tools.base import BaseTool

class ToolRegistry:
    """
    Tool registry and manager.
    Allows adding new tools without modifying the core engine.
    """
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Register a new tool in the system."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get_tool(self, tool_name: str) -> BaseTool:
        """Look up a tool by name."""
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' not found in registry.")
        return self._tools[tool_name]

    def get_all_schemas(self) -> list:
        """Return all tool schemas to inform the LLM of available capabilities."""
        return [tool.get_schema() for tool in self._tools.values()]

# Global singleton instance
registry = ToolRegistry()
