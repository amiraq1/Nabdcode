from typing import Dict
from tools.base import BaseTool

class ToolRegistry:
    """
    Tool registry and manager.
    Allows adding new tools without modifying the core engine.
    """
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, name_or_tool: Any, tool: Optional[Any] = None, **kwargs):
        """Register a new tool in the system."""
        if tool is None:
            tool_obj = name_or_tool
        else:
            tool_obj = tool
        name = getattr(tool_obj, "name", None) or (name_or_tool if isinstance(name_or_tool, str) else str(tool_obj))
        if name in self._tools and kwargs.get("overwrite", False) is False:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = tool_obj

    def get_tool(self, tool_name: str) -> BaseTool:
        """Look up a tool by name."""
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' not found in registry.")
        return self._tools[tool_name]

    def __contains__(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def get_all_schemas(self) -> list:
        """Return all tool schemas to inform the LLM of available capabilities."""
        return [tool.get_schema() if hasattr(tool, "get_schema") else {"name": getattr(tool, "name", str(tool)), "description": getattr(tool, "description", "")} for tool in self._tools.values()]

# Global singleton instance
registry = ToolRegistry()
tool_registry = registry
