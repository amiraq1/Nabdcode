# core/hybrid_retriever.py
from datetime import datetime, timezone
from typing import List, Tuple, Optional
from core.storage import MemoryStore, MemoryChunk
from core.semantic_index import TfIdfIndex


class HybridRetriever:
    """Combines keyword BM25-like search with semantic TF-IDF search"""

    def __init__(self, memory_store: MemoryStore):
        self.store = memory_store
        self.semantic_index = TfIdfIndex()
        self._build_index()

    def _build_index(self) -> None:
        """Rebuild semantic index from all chunks"""
        chunks = self.store.get_all()
        self.semantic_index.index_chunks(chunks)

    def search(
        self,
        query: str,
        top_k: int = 5,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        time_decay: bool = True
    ) -> List[dict]:
        """
        Hybrid search: semantic + keyword boost + time decay

        Args:
            query: search query
            top_k: number of results
            semantic_weight: weight for semantic similarity (0-1)
            keyword_weight: weight for exact keyword matches (0-1)
            time_decay: boost recent memories
        """
        chunks = self.store.get_all()
        if not chunks:
            return []

        # Semantic search
        semantic_results = self.semantic_index.search(query, chunks, top_k=top_k * 2)
        semantic_scores = {chunk.id: score for chunk, score in semantic_results}

        # Keyword search (simple exact match boost)
        query_terms = set(query.lower().split())
        keyword_scores = {}
        for chunk in chunks:
            text_lower = chunk.text.lower()
            matches = sum(1 for term in query_terms if term in text_lower)
            keyword_scores[chunk.id] = matches / max(len(query_terms), 1)

        # Combine scores
        combined = []
        for chunk in chunks:
            sem_score = semantic_scores.get(chunk.id, 0.0)
            kw_score = keyword_scores.get(chunk.id, 0.0)

            score = (semantic_weight * sem_score) + (keyword_weight * kw_score)

            # Time decay: recent memories get slight boost
            if time_decay:
                age_hours = self._get_age_hours(chunk.timestamp)
                decay_factor = max(0.5, 1.0 - (age_hours / 168.0))  # 1 week half-life
                score *= decay_factor

            if score > 0.01:  # threshold
                combined.append({
                    "id": chunk.id,
                    "text": chunk.text,
                    "score": round(score, 4),
                    "timestamp": chunk.timestamp,
                    "metadata": chunk.metadata,
                })

        combined.sort(key=lambda x: (x["score"], x["timestamp"]), reverse=True)
        return combined[:top_k]

    def _get_age_hours(self, timestamp: str) -> float:
        """Calculate age in hours from ISO timestamp"""
        try:
            ts = datetime.fromisoformat(timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ts
            return max(0.0, delta.total_seconds() / 3600.0)
        except Exception:
            return 0.0

    def add_memory(self, text: str, metadata: Optional[dict] = None) -> MemoryChunk:
        """Add memory and update index"""
        chunk = self.store.add(text, metadata)
        self.semantic_index.index_chunks(self.store.get_all())  # incremental rebuild
        return chunk
