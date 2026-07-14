from __future__ import annotations

from typing import Final, Any
from tools.base import BaseTool
from tools.models import ToolResult


def execute_search_memory(args: dict, memory_manager: Any) -> str:
    """
    Deep memory retrieval tool for the agent, uses hybrid search engine.
    """
    query = args.get("query", "")
    limit = args.get("limit", 5)

    if memory_manager is None:
        from core.memory import MemoryManager
        memory_manager = MemoryManager()

    results = memory_manager.hybrid_search(query, limit=limit)

    if not results:
        return f"No memories or prior context found for: {query}"

    memory_report = f"🔍 Memory search results for '{query}':\n\n"
    for i, res in enumerate(results, 1):
        role = res.get("role", "unknown")
        content = res.get("content", "")
        if len(content) > 1000:
            content = content[:1000] + "\n... [truncated]"

        memory_report += f"[{i}] (Role: {role}):\n{content}\n"
        memory_report += "-" * 30 + "\n"

    return memory_report.strip()


class SearchMemoryTool(BaseTool):
    """
    Deep memory retrieval tool for the agent, uses MemoryManager hybrid search.
    """

    name: Final[str] = "search_memory"
    description: Final[str] = (
        "Search deep semantic memory and past conversation context using hybrid search."
    )

    def __init__(self, memory_manager: Any = None):
        super().__init__()
        self.memory_manager = memory_manager

    def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query")

        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                success=False,
                stderr="Missing or invalid 'query' argument for search_memory.",
                returncode=-1,
                status="error",
            )

        try:
            report = execute_search_memory(kwargs, self.memory_manager)
            return ToolResult(
                success=True,
                stdout=report,
                returncode=0,
                status="success",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                stderr=f"Error executing search_memory: {exc}",
                returncode=-1,
                status="error",
            )
