"""Capability policy for delegated sub-agent loops.

The ``task`` tool is intended for research, exploration, and verification.
A delegated loop must therefore not inherit the main agent's broad ability to
modify files, execute shell commands, or spawn another delegated loop.

This module enforces the policy twice:

* the sub-agent sees only a filtered tool registry;
* the file-system entry in that registry accepts read/list actions only.

Keeping the policy beside the runner makes the restriction independent from
prompt wording and prevents a model from reaching an omitted tool by name.
"""

from __future__ import annotations

from typing import Any, Final, Iterable

from tools.base import BaseTool
from tools.models import ToolResult


# The delegated ``task`` tool is documented as a research/exploration helper.
# Keep its default surface intentionally read-only and do not include ``task``
# itself: nested delegation compounds cost, latency, and authority without a
# supervising consent loop.
DEFAULT_SUBAGENT_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "file_system",
        "search_memory",
        "web_search",
        "code_intelligence",
    }
)

_READ_ONLY_FILE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "read",
        "read_many",
        "list",
    }
)


class ReadOnlyFileSystemTool(BaseTool):
    """Expose the existing file tool while enforcing read/list-only actions."""

    name: Final[str] = "file_system"
    description: Final[str] = (
        "Read or list files inside the workspace for delegated research. "
        "Allowed actions: 'read', 'read_many', and 'list'. "
        "This delegated agent cannot edit, write, append, or replace files."
    )

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped

    @property
    def args_schema(self):
        return getattr(self._wrapped, "args_schema", None)

    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action", "")).strip().lower()
        if action not in _READ_ONLY_FILE_ACTIONS:
            return ToolResult(
                success=False,
                stderr=(
                    "Sub-agent policy denied file_system action "
                    f"{action!r}. Delegated tasks are read-only; use one of: "
                    + ", ".join(sorted(_READ_ONLY_FILE_ACTIONS))
                    + "."
                ),
                returncode=-1,
                status="policy_denied",
                metadata={"blocked_by": "subagent_policy", "action": action},
            )
        return self._wrapped(**kwargs)


class RestrictedToolRegistry:
    """Registry view that exposes only explicitly approved sub-agent tools.

    It follows the small structural registry contract used by ``ExecutionLoop``
    and ``Dispatcher``.  The wrapper is a new mapping, so both tool-schema
    generation and dispatch resolve against the same limited surface.
    """

    def __init__(self, source_registry: Any, allowed_tools: Iterable[str] = DEFAULT_SUBAGENT_TOOLS) -> None:
        self._tools: dict[str, Any] = {}
        for name in allowed_tools:
            if name not in source_registry:
                continue
            tool = source_registry.get_tool(name)
            if name == "file_system":
                tool = ReadOnlyFileSystemTool(tool)
            self._tools[name] = tool

    def get_tool(self, tool_name: str) -> Any:
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' is not permitted for delegated sub-agents.")
        return self._tools[tool_name]

    def __contains__(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def get_all_schemas(self) -> list[dict[str, Any]]:
        return [
            tool.get_schema()
            if hasattr(tool, "get_schema")
            else {
                "name": getattr(tool, "name", str(tool)),
                "description": getattr(tool, "description", ""),
            }
            for tool in self._tools.values()
        ]

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.items())
