# core/semantic_index.py
import math
import re
from collections import Counter
from typing import List, Tuple, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.storage import MemoryChunk
else:
    MemoryChunk = Any


class TfIdfIndex:
    """Lightweight TF-IDF + cosine similarity for semantic search"""

    _VERSION: str = "1.0"

    def __init__(self):
        self._doc_freq: Counter = Counter()
        self._doc_count = 0
        self._vocab = {}
        self._stored_version: str = self._VERSION

    def index_chunks(self, chunks: List[MemoryChunk]) -> None:
        """Build TF-IDF index from chunks"""
        self._doc_count = len(chunks)
        self._doc_freq = Counter()

        for chunk in chunks:
            tokens = self._tokenize(chunk.text)
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._doc_freq[token] += 1

    # ── ARCH-1: Versioning & persistence ────────────────────────────────

    @property
    def version(self) -> str:
        """Return the current index format version."""
        return self._VERSION

    def needs_rebuild(self) -> bool:
        """Return True if the stored index version differs from the current version.

        When the index format changes (e.g. tokenizer, TF weighting, or
        serialization schema), ``_VERSION`` is bumped.  A persisted index
        whose ``_stored_version`` does not match is considered stale and
        must be rebuilt from source chunks.
        """
        return self._stored_version != self._VERSION

    def serialize(self) -> dict:
        """Serialize the index to a version-tagged dict for disk persistence."""
        return {
            "version": self._VERSION,
            "doc_count": self._doc_count,
            "doc_freq": dict(self._doc_freq),
            "vocab": self._vocab,
        }

    def deserialize(self, data: dict) -> bool:
        """Load index state from a serialized dict.

        Returns True if the version matched and the index was loaded
        successfully; False if the version is stale (caller should rebuild).
        """
        if not isinstance(data, dict):
            return False
        stored = data.get("version", "")
        if stored != self._VERSION:
            self._stored_version = stored
            return False
        self._doc_count = data.get("doc_count", 0)
        self._doc_freq = Counter(data.get("doc_freq", {}))
        self._vocab = data.get("vocab", {})
        self._stored_version = stored
        return True

    def search(self, query: str, chunks: List[MemoryChunk], top_k: int = 5) -> List[Tuple[MemoryChunk, float]]:
        """Search chunks by cosine similarity"""
        if not chunks:
            return []

        query_tokens = self._tokenize(query)
        query_tf = self._compute_tf(query_tokens)

        scores = []
        for chunk in chunks:
            doc_tokens = self._tokenize(chunk.text)
            doc_tf = self._compute_tf(doc_tokens)

            # Cosine similarity between query TF and doc TF vectors
            score = self._cosine_similarity(query_tf, doc_tf)
            if score > 0:
                scores.append((chunk, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace + punctuation tokenizer (Arabic-aware)"""
        text = text.lower()
        # Keep Arabic letters, numbers, and common chars
        tokens = re.findall(r'\b\w+\b', text)
        return [t for t in tokens if len(t) > 1]

    def _compute_tf(self, tokens: List[str]) -> dict:
        """Compute term frequency"""
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1
        return {term: count / total for term, count in tf.items()}

    def _cosine_similarity(self, vec1: dict, vec2: dict) -> float:
        """Compute cosine similarity between two sparse TF vectors"""
        common_keys = set(vec1.keys()) & set(vec2.keys())
        if not common_keys:
            return 0.0

        dot_product = sum(vec1[k] * vec2[k] for k in common_keys)
        mag1 = math.sqrt(sum(v ** 2 for v in vec1.values()))
        mag2 = math.sqrt(sum(v ** 2 for v in vec2.values()))

        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot_product / (mag1 * mag2)
