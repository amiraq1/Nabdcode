# tools/search_memory.py
"""Hybrid semantic + keyword memory search tool with Pydantic self-validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Type

from tools.base import BaseTool, BaseModel, Field
from tools.models import ToolResult
from core.hybrid_retriever import HybridRetriever
from core.storage import MemoryStore


# ── Pydantic argument schema ──
# tools.base re-exports a working BaseModel stub when real pydantic-core is
# unavailable (e.g. Termux/Android), so the class can be defined unconditionally.

class SearchMemoryArgs(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Natural-language search query for semantic memory retrieval.",
    )
    limit: int = Field(
        5,
        ge=1,
        le=50,
        description="Maximum number of memory results to return (1–50).",
    )


class SearchMemoryTool(BaseTool):
    """Search local semantic memory using hybrid keyword + vector retrieval.

    Maintains a persistent ``MemoryStore`` backed by JSONL and a
    ``HybridRetriever`` that combines TF-IDF keyword scoring with
    time-decay re-ranking.
    """

    name: str = "search_memory"
    description: str = (
        "Search local semantic memory (hybrid keyword + vector) for prior "
        "context, lessons, or historical information from this agent session."
    )

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        memory_manager: Any = None,
    ) -> None:
        super().__init__()
        if storage_dir is None:
            storage_dir = Path.cwd() / ".nabd" / "memory"
        storage_dir = Path(storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = storage_dir / "memory.jsonl"
        self.store = MemoryStore(self.storage_path)
        self.retriever = HybridRetriever(self.store)
        self.memory_manager = memory_manager

    # ── Pydantic self-validation ──────────────────────────────────────

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return SearchMemoryArgs

    # ── Unified execution path ────────────────────────────────────────

    def execute_with_args(self, args: Any) -> ToolResult:
        """Execute hybrid memory search with validated *args*."""
        # Support both SearchMemoryArgs (Pydantic) and raw-dict fallback
        if isinstance(args, dict):
            query = args.get("query", "")
            limit = int(args.get("limit", args.get("top_k", 5)))
        else:
            query = args.query
            limit = args.limit

        try:
            results = self.retriever.search(query, top_k=limit)
            lines: list[str] = [f"🔍 Memory search results for '{query}':\n"]
            for i, r in enumerate(results, 1):
                lines.append(
                    f"[{i}] (Score: {r['score']:.3f}):\n{r['text']}\n"
                    + "-" * 30
                )
            if not results:
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

    # ── Legacy entry point (backward compatible) ──────────────────────

    def execute(self, **kwargs: Any) -> ToolResult:
        """Legacy ``**kwargs`` entry point — delegates to ``execute_with_args``."""
        query = kwargs.get("query", "")
        limit = int(kwargs.get("top_k", kwargs.get("limit", 5)))
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                success=False,
                stderr="Missing or invalid 'query' argument for search_memory.",
                returncode=-1,
                status="error",
            )
        return self.execute_with_args(SearchMemoryArgs(query=query, limit=limit))

    # ── External memory ingestion ─────────────────────────────────────

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        """Add a new memory entry (called by other tools after operations)."""
        self.retriever.add_memory(text, metadata)
