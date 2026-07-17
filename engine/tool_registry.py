from typing import Any, Dict, Optional
from core.kernel.protocols import ToolCallable

class ToolRegistry:
    """
    Tool registry and manager.
    Allows adding new tools without modifying the core engine.
    Supports dynamic schema generation from Pydantic ``args_schema``.
    """
    def __init__(self):
        self._tools: Dict[str, ToolCallable] = {}

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

    def get_tool(self, tool_name: str) -> ToolCallable:
        """Look up a tool by name."""
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' not found in registry.")
        return self._tools[tool_name]

    def __contains__(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def get_all_schemas(self) -> list:
        """Return all tool schemas to inform the LLM of available capabilities.

        When a tool declares a Pydantic ``args_schema``, the JSON Schema
        is generated automatically via ``model_json_schema()``.  Tools
        without Pydantic schemas fall back to ``get_schema()`` (name + desc).
        """
        schemas = []
        for tool in self._tools.values():
            schema = tool.get_schema() if hasattr(tool, "get_schema") else {
                "name": getattr(tool, "name", str(tool)),
                "description": getattr(tool, "description", ""),
            }
            schemas.append(schema)
        return schemas

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.items())


# Global singleton instance
registry = ToolRegistry()
tool_registry = registry
