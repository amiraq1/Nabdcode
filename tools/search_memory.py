# tools/search_memory.py
from pathlib import Path
from typing import Optional, Any
from core.hybrid_retriever import HybridRetriever, MemoryStore
from tools.base import BaseTool
from tools.models import ToolResult


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = "Search local semantic memory (hybrid keyword + vector)"

    def __init__(self, storage_dir: Optional[Path] = None, memory_manager: Any = None):
        super().__init__()
        if storage_dir is None:
            storage_dir = Path.cwd() / ".nabd" / "memory"
        storage_dir = Path(storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = storage_dir / "memory.jsonl"
        self.store = MemoryStore(self.storage_path)
        self.retriever = HybridRetriever(self.store)
        self.memory_manager = memory_manager

    def __call__(self, query: str, top_k: int = 5) -> dict:
        """
        Search memory with hybrid retrieval.

        Args:
            query: natural language query
            top_k: number of results (default 5, max 10)
        """
        top_k = min(max(top_k, 1), 10)
        results = self.retriever.search(query, top_k=top_k)

        return {
            "tool": "search_memory",
            "results": [
                {
                    "id": r["id"],
                    "text": r["text"],
                    "score": r["score"],
                    "timestamp": r["timestamp"],
                }
                for r in results
            ],
            "total_chunks": len(self.store.get_all()),
        }

    def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        top_k = kwargs.get("top_k", kwargs.get("limit", 5))
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                success=False,
                stderr="Missing or invalid 'query' argument for search_memory.",
                returncode=-1,
                status="error",
            )
        try:
            res = self(query=query, top_k=int(top_k))
            lines = [f"🔍 Memory search results for '{query}':\n"]
            for i, r in enumerate(res["results"], 1):
                lines.append(f"[{i}] (Score: {r['score']}):\n{r['text']}\n" + "-" * 30)
            if not res["results"]:
                lines.append(f"No memories or prior context found for: {query}")
            return ToolResult(
                success=True,
                stdout="\n".join(lines).strip(),
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

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        """Add new memory (called by other tools after operations)"""
        self.retriever.add_memory(text, metadata)
