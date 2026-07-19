"""tools/rag_search.py — Pure-Python Local RAG Search Tool.

Architecture (3-Layer RAG Stack):
  1. Embedder:  n-gram hash → 256-dim numpy array (HashEmbedder)
  2. Index:     NumpyVectorIndex (pure-Python IdMapIndex-compatible)
  3. Vault:     JSON text store (TextVault)

Hybrid retrieval: Vector cosine (semantic) + BM25 keyword (exact symbol match).
The BM25 layer guarantees that rare code symbols like ``list(self._subscribers)``
surface ``core/kernel/events.py`` even when the hash embedder spreads frequency.

Swap path: when turbovec+nomic-embed work on Termux, replace only the
internals of HashEmbedder and NumpyVectorIndex — the LocalKnowledgeBase
orchestrator, ingestion pipeline, and tool interface stay unchanged.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Optional, Type

import numpy as np

from tools.base import BaseTool, BaseModel, Field
from tools.models import ToolResult


# ── Defaults ────────────────────────────────────────────────────────────────

_DEFAULT_DIM: int = 256
_STORE_DIR: str = ".nabd/rag"
_VAULT_FILE: str = "vault.json"
_INDEX_FILE: str = "index"
_CHUNK_SIZE: int = 384
_CHUNK_OVERLAP: int = 160


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1 — Hash Embedder
# ═══════════════════════════════════════════════════════════════════════════

class HashEmbedder:
    """Character n-gram hash embedder → 256-dim float32 vector.

    Uses character trigrams & 4-grams with dual-hash seeds for collision
    reduction, plus word-level tokens at 1/3 sampling rate. L2-normalised.
    Drop-in for nomic-embed-text-v1.5 GGUF in the future.
    """

    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float64)
        text_lower = text.lower()

        for n in (3, 4):
            for i in range(len(text_lower) - n + 1):
                ngram = text_lower[i:i + n]
                h1 = int(hashlib.md5((ngram + "_h1").encode()).hexdigest()[:8], 16)
                h2 = int(hashlib.md5((ngram + "_h2").encode()).hexdigest()[:8], 16)
                vec[h1 % self.dim] += 1.0
                vec[h2 % self.dim] += 0.5

        tokens = re.findall(r'\b\w+\b', text_lower)
        for token in tokens:
            h = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
            if h % 3 == 0:
                vec[h % self.dim] += 0.8

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.astype(np.float32)

    def __call__(self, text: str) -> np.ndarray:
        return self.embed(text)


# ═══════════════════════════════════════════════════════════════════════════
# Layer 2 — NumpyVectorIndex (IdMapIndex-compatible)
# ═══════════════════════════════════════════════════════════════════════════

class NumpyVectorIndex:
    """Pure-Python vector index backed by numpy arrays.

    Mirrors turbovec.IdMapIndex API:
        add(id, vector) / search(query, k) → (scores, ids)
        save(path) / load(path)

    Replace with turbovec when available:
        >>> from turbovec import IdMapIndex, TurboQuantIndex
        >>> core = TurboQuantIndex.empty(dim=768, bit_width=4)
        >>> self.index = IdMapIndex(core)
    """

    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        self.dim = dim
        self._vectors: list[np.ndarray] = []
        self._ids: list[str] = []
        self._lock = threading.Lock()

    @classmethod
    def empty(cls, dim: int = _DEFAULT_DIM) -> NumpyVectorIndex:
        return cls(dim=dim)

    def add(self, id: str, vector: np.ndarray) -> None:
        with self._lock:
            vec = vector.astype(np.float32).copy()
            if id in self._ids:
                self._vectors[self._ids.index(id)] = vec
            else:
                self._ids.append(str(id))
                self._vectors.append(vec)

    def add_many(self, ids: list[str], vectors: np.ndarray) -> None:
        with self._lock:
            for i, id_ in enumerate(ids):
                vec = vectors[i].astype(np.float32).copy()
                if id_ in self._ids:
                    self._vectors[self._ids.index(id_)] = vec
                else:
                    self._ids.append(str(id_))
                    self._vectors.append(vec)

    def search(self, query_vector: np.ndarray, k: int = 5) -> tuple[np.ndarray, list[str]]:
        qv = query_vector.astype(np.float32).flatten()
        with self._lock:
            n = len(self._vectors)
            if n == 0:
                return np.array([], dtype=np.float32), []
            mat = np.stack(self._vectors, axis=0)

        scores = mat @ qv  # cosine (all vectors L2-normalised)
        if len(scores) <= k:
            idx = np.argsort(-scores)
        else:
            idx = np.argpartition(-scores, k)[:k]
            idx = idx[np.argsort(-scores[idx])]

        with self._lock:
            result_ids = [self._ids[i] for i in idx.tolist()]
        return scores[idx].astype(np.float32), result_ids

    def __len__(self) -> int:
        with self._lock:
            return len(self._ids)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            mat = np.stack(self._vectors, axis=0) if self._vectors else np.zeros((0, self.dim), dtype=np.float32)
            ids = list(self._ids)
        np.save(str(path.with_suffix(".npy")), mat)
        (path.with_suffix(".ids.json")).write_text(
            json.dumps({"ids": ids, "dim": self.dim}, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> NumpyVectorIndex:
        path = Path(path)
        idx = cls.__new__(cls)
        idx._lock = threading.Lock()
        mat = np.load(str(path.with_suffix(".npy")))
        meta = json.loads((path.with_suffix(".ids.json")).read_text(encoding="utf-8"))
        idx.dim = meta.get("dim", mat.shape[1])
        idx._vectors = [mat[i].copy() for i in range(mat.shape[0])]
        idx._ids = list(meta.get("ids", []))
        return idx


# ═══════════════════════════════════════════════════════════════════════════
# Layer 2b — BM25 Keyword Index (hybrid exact-symbol retrieval)
# ═══════════════════════════════════════════════════════════════════════════

class Bm25KeywordIndex:
    """BM25 sparse index for exact code-symbol retrieval.

    Guarantees that rare tokens (e.g. ``_subscribers``, ``emit``) surface the
    right file even when the dense hash embedder spreads term frequency across
    many modules. Mirrors TfIdfIndex scoring but with IDF + length norm (BM25).
    """

    def __init__(self) -> None:
        self._doc_freq: Counter = Counter()
        self._doc_count: int = 0
        self._doc_ids: list[str] = []
        self._doc_tokens: list[list[str]] = []
        self._avg_len: float = 0.0
        self._lock = threading.Lock()
        self._k1: float = 1.5
        self._b: float = 0.75

    def save(self, path: Path) -> None:
        """Persist BM25 state (doc_ids + tokenised docs + freq stats)."""
        payload = {
            "doc_ids": self._doc_ids,
            "doc_tokens": self._doc_tokens,
            "doc_freq": dict(self._doc_freq),
            "doc_count": self._doc_count,
            "avg_len": self._avg_len,
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    def load(self, path: Path) -> None:
        """Restore BM25 state from a saved JSON file."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self._doc_ids = payload["doc_ids"]
        self._doc_tokens = payload["doc_tokens"]
        self._doc_freq = Counter(payload["doc_freq"])
        self._doc_count = payload["doc_count"]
        self._avg_len = payload["avg_len"]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        text = text.lower()
        # Keep code symbols: word chars + dotted/underscored identifiers
        tokens = re.findall(r'[a-z0-9_]+', text)
        return [t for t in tokens if len(t) > 1]

    def add(self, chunk_id: str, text: str) -> None:
        with self._lock:
            toks = self._tokenize(text)
            self._doc_ids.append(str(chunk_id))
            self._doc_tokens.append(toks)
            for t in set(toks):
                self._doc_freq[t] += 1
            self._doc_count = len(self._doc_ids)
            total = sum(len(d) for d in self._doc_tokens)
            self._avg_len = total / self._doc_count if self._doc_count else 0.0

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []
        with self._lock:
            doc_ids = list(self._doc_ids)
            doc_tokens = list(self._doc_tokens)
            doc_count = self._doc_count
            doc_freq = dict(self._doc_freq)
            avg_len = self._avg_len
        scores: list[tuple[str, float]] = []
        for i, toks in enumerate(doc_tokens):
            dl = len(toks)
            tf_counts = Counter(toks)
            score = 0.0
            for qt in q_tokens:
                if qt not in tf_counts:
                    continue
                df = doc_freq.get(qt, 0)
                if df == 0:
                    continue
                idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)
                tf = tf_counts[qt]
                denom = tf + self._k1 * (1 - self._b + self._b * (dl / avg_len if avg_len else 1))
                score += idf * (tf * (self._k1 + 1)) / denom
            if score > 0:
                scores.append((doc_ids[i], score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ═══════════════════════════════════════════════════════════════════════════
# Layer 3 — TextVault (JSON-backed)
# ═══════════════════════════════════════════════════════════════════════════

class TextVault:
    """Persistent JSON store mapping chunk hashes → {text, source}."""

    def __init__(self, vault_path: Path) -> None:
        self._path = Path(vault_path)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._data = raw.get("chunks", {})
            except (json.JSONDecodeError, KeyError):
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"version": 1, "chunks": self._data}, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def put(self, chunk_id: str, text: str, source: str = "") -> None:
        with self._lock:
            self._data[chunk_id] = {"text": text, "source": source or "unknown"}
            self._save()

    def get(self, chunk_id: str) -> str:
        with self._lock:
            return self._data.get(chunk_id, {}).get("text", "")

    def get_all_with_sources(self, ids: list[str]) -> list[dict[str, str]]:
        with self._lock:
            return [{"id": i, "text": self._data.get(i, {}).get("text", ""),
                     "source": self._data.get(i, {}).get("source", "unknown")} for i in ids]

    def size(self) -> int:
        with self._lock:
            return len(self._data)


# ═══════════════════════════════════════════════════════════════════════════
# LocalKnowledgeBase — Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

class LocalKnowledgeBase:
    """Orchestrates embedder → index → vault for local RAG."""

    def __init__(self, workspace_root: str | Path = ".", dim: int = _DEFAULT_DIM,
                 chunk_size: int = _CHUNK_SIZE, chunk_overlap: int = _CHUNK_OVERLAP) -> None:
        self.dim = dim
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        root = Path(workspace_root).resolve()
        self._store_dir = root / _STORE_DIR
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._embedder = HashEmbedder(dim=dim)
        index_path = self._store_dir / _INDEX_FILE
        try:
            self._index = NumpyVectorIndex.load(index_path)
        except (FileNotFoundError, ValueError, OSError):
            self._index = NumpyVectorIndex.empty(dim=dim)
        self._vault = TextVault(self._store_dir / _VAULT_FILE)
        self._bm25 = Bm25KeywordIndex()
        # Load BM25 index from disk if present (it is NOT persisted by
        # NumpyVectorIndex, so we must restore it separately or rebuild it).
        bm25_path = self._store_dir / (_INDEX_FILE + ".bm25.json")
        if bm25_path.exists():
            try:
                self._bm25.load(bm25_path)
            except (json.JSONDecodeError, KeyError, OSError):
                self._bm25 = Bm25KeywordIndex()

    def ingest_text(self, text: str, source: str = "") -> int:
        chunks = self._chunk_text(text)
        for chunk_text in chunks:
            chunk_id = self._hash_chunk(chunk_text, source)
            self._index.add(chunk_id, self._embedder(chunk_text))
            self._bm25.add(chunk_id, chunk_text)
            self._vault.put(chunk_id, chunk_text, source=source)
        self._index.save(self._store_dir / _INDEX_FILE)
        self._bm25.save(self._store_dir / (_INDEX_FILE + ".bm25.json"))
        return len(chunks)

    def ingest_file(self, file_path: str | Path, source: str = "") -> int:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        return self.ingest_text(text, source=source or str(path))

    def search(self, query: str, k: int = 3, max_chars_per_chunk: int = 1200,
                vector_weight: float = 0.4, keyword_weight: float = 0.6) -> str:
        """Hybrid search: vector cosine + BM25 keyword, merged by score.

        The BM25 layer (weight 0.6) ensures exact code symbols surface the
        right file; the vector layer (weight 0.4) adds semantic context. Returns
        FULL chunk text so the agent reads real code, not a 3-line teaser.
        """
        if not query or not query.strip():
            return "Error: empty query."
        query_vec = self._embedder(query)

        # Vector scores
        v_scores, v_ids = self._index.search(query_vec, k=max(k * 3, 10))
        v_map = {cid: float(v_scores[i]) for i, cid in enumerate(v_ids)}
        v_max = max(v_map.values()) if v_map else 1.0

        # BM25 scores
        k_results = self._bm25.search(query, top_k=max(k * 3, 10))
        k_map = {cid: score for cid, score in k_results}
        k_max = max(k_map.values()) if k_map else 1.0

        # Merge: union of candidate IDs
        all_ids = list(dict.fromkeys(list(v_map.keys()) + list(k_map.keys())))
        merged: list[tuple[str, float]] = []
        for cid in all_ids:
            vs = (v_map.get(cid, 0.0) / v_max) * vector_weight if v_max > 0 else 0.0
            ks = (k_map.get(cid, 0.0) / k_max) * keyword_weight if k_max > 0 else 0.0
            merged.append((cid, vs + ks))

        merged.sort(key=lambda x: x[1], reverse=True)
        top_ids = [cid for cid, _ in merged[:k]]

        if not top_ids:
            return (
                f"No code context found for: '{query}'\n"
                f"Tip: ingest source files first with action='ingest_file'."
            )

        results = self._vault.get_all_with_sources(top_ids)
        blocks: list[str] = []
        for i, result in enumerate(results, 1):
            source = result.get("source", "?")
            text = result.get("text", "")
            if len(text) > max_chars_per_chunk:
                text = text[:max_chars_per_chunk] + "\n... (truncated)"
            blocks.append(
                f"[{i}] Source: {source}\n"
                f"{'─' * 40}\n"
                f"{text}"
            )
        formatted_context = "\n\n--- CODE SNIPPET ---\n\n".join(blocks)
        return (
            f"Found the following context in the codebase for query '{query}':\n\n"
            f"{formatted_context}"
        )

    def search_raw(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        query_vec = self._embedder(query)
        scores, ids = self._index.search(query_vec, k=k)
        results = self._vault.get_all_with_sources(ids)
        return [{"score": float(scores[i]), **result} for i, result in enumerate(results)]

    def _chunk_text(self, text: str) -> list[str]:
        if len(text) <= self.chunk_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break
            nl = text.rfind("\n", start, end)
            if nl > start + self.chunk_size // 2:
                chunks.append(text[start:nl])
                start = nl + 1
            else:
                chunks.append(text[start:end])
                start = end - self.chunk_overlap
        return chunks

    @staticmethod
    def _hash_chunk(text: str, source: str) -> str:
        return hashlib.sha256(f"{source}::{text[:80]}".encode()).hexdigest()[:16]

    def stats(self) -> dict[str, Any]:
        return {"chunks": len(self._index), "dim": self.dim, "vault_size": self._vault.size()}


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════════

class RagIngestArgs(BaseModel):
    action: str = Field("search", pattern="^(search|ingest_file|ingest_text|stats)$",
                        description="Action: search, ingest_file, ingest_text, or stats.")
    query: str = Field("", max_length=500, description="Search query (required for action='search').")
    k: int = Field(3, ge=1, le=20, description="Number of top results (1–20).")
    file_path: str = Field("", max_length=500, description="Path to file for ingest_file.")
    text: str = Field("", max_length=10000, description="Raw text for ingest_text.")
    source: str = Field("", max_length=200, description="Source label for ingested content.")


# ═══════════════════════════════════════════════════════════════════════════
# Tool
# ═══════════════════════════════════════════════════════════════════════════

class RagSearchTool(BaseTool):
    """Search or update the local RAG knowledge base using semantic vector search."""

    name: str = "search_knowledge_base"
    description: str = (
        "Search the local codebase knowledge base using semantic vector search. "
        "Returns code snippets most relevant to your query. Supports actions: "
        "search (default), ingest_file, ingest_text, stats."
    )

    def __init__(self, workspace_root: str | Path = ".") -> None:
        super().__init__()
        self._workspace_root = str(workspace_root)
        self._kb: LocalKnowledgeBase | None = None

    @property
    def _get_kb(self) -> LocalKnowledgeBase:
        if self._kb is None:
            self._kb = LocalKnowledgeBase(workspace_root=self._workspace_root)
        return self._kb

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return RagIngestArgs

    def execute_with_args(self, args: Any) -> ToolResult:
        action = args.action if hasattr(args, 'action') else args.get("action", "search")
        try:
            if action == "search":
                return self._execute_search(args)
            elif action == "ingest_file":
                return self._execute_ingest_file(args)
            elif action == "ingest_text":
                return self._execute_ingest_text(args)
            elif action == "stats":
                return self._execute_stats()
            else:
                return ToolResult(success=False, stderr=f"Unknown action: {action}", returncode=-1, status="error")
        except Exception as exc:
            return ToolResult(success=False, stderr=f"RAG error: {exc}", returncode=-1, status="error")

    def _execute_search(self, args: Any) -> ToolResult:
        query = args.query if hasattr(args, 'query') else args.get("query", "")
        k = int(args.k if hasattr(args, 'k') else args.get("k", 3))
        if not query:
            return ToolResult(success=False, stderr="Missing 'query' for search.", returncode=-1, status="error")
        kb = self._get_kb
        result = kb.search(query, k=k)
        stats = kb.stats()
        return ToolResult(success=True, stdout=result, returncode=0, status="success",
                          metadata={"action": "search", "query": query, "k": k, "chunks": stats["chunks"]})

    def _execute_ingest_file(self, args: Any) -> ToolResult:
        fp = args.file_path if hasattr(args, 'file_path') else args.get("file_path", "")
        src = args.source if hasattr(args, 'source') else args.get("source", "")
        if not fp:
            return ToolResult(success=False, stderr="Missing 'file_path'.", returncode=-1, status="error")
        full = Path(fp) if Path(fp).is_absolute() else Path(self._workspace_root) / fp
        if not full.exists():
            return ToolResult(success=False, stderr=f"File not found: {fp}", returncode=-1, status="error")
        kb = self._get_kb
        n = kb.ingest_file(str(full), source=src or fp)
        s = kb.stats()
        return ToolResult(success=True, stdout=f"✅ Ingested {full.name}: {n} chunks. Total: {s['chunks']}.",
                          returncode=0, status="success",
                          metadata={"action": "ingest_file", "file": fp, "chunks_added": n, "total": s["chunks"]})

    def _execute_ingest_text(self, args: Any) -> ToolResult:
        text = args.text if hasattr(args, 'text') else args.get("text", "")
        src = args.source if hasattr(args, 'source') else args.get("source", "")
        if not text:
            return ToolResult(success=False, stderr="Missing 'text'.", returncode=-1, status="error")
        kb = self._get_kb
        n = kb.ingest_text(text, source=src)
        s = kb.stats()
        return ToolResult(success=True, stdout=f"✅ Ingested text: {n} chunks. Total: {s['chunks']}.",
                          returncode=0, status="success",
                          metadata={"action": "ingest_text", "chunks_added": n, "total": s["chunks"]})

    def _execute_stats(self) -> ToolResult:
        s = self._get_kb.stats()
        return ToolResult(success=True,
                          stdout=f"📊 RAG KB: {s['chunks']} chunks, {s['dim']}d, {s['vault_size']} vault entries.",
                          returncode=0, status="success", metadata=s)

    def execute(self, **kwargs: Any) -> ToolResult:
        return self.execute_with_args(kwargs)


__all__ = ["HashEmbedder", "NumpyVectorIndex", "TextVault",
           "LocalKnowledgeBase", "RagIngestArgs", "RagSearchTool"]
