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


from tools.search_memory import SearchMemoryTool
