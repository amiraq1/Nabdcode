# core/memory_store.py
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta


@dataclass
class MemoryChunk:
    id: str
    text: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict = field(default_factory=dict)
    embedding: Optional[List[float]] = None  # cached vector


class MemoryStore:
    def __init__(self, storage_path: Path):
        self.storage_path = Path(storage_path)
        self._chunks: List[MemoryChunk] = []
        self._load()

    def _load(self) -> None:
        """Load chunks from JSONL file"""
        if not self.storage_path.exists():
            return
        for line in self.storage_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            self._chunks.append(MemoryChunk(**data))

    def add(self, text: str, metadata: Optional[dict] = None) -> MemoryChunk:
        """Add new memory chunk"""
        now = datetime.utcnow()
        if self._chunks and self._chunks[-1].timestamp >= now.isoformat():
            try:
                last_dt = datetime.fromisoformat(self._chunks[-1].timestamp)
                now = max(now, last_dt + timedelta(milliseconds=1))
            except Exception:
                pass
        chunk = MemoryChunk(
            id=f"mem_{len(self._chunks)}_{int(now.timestamp())}",
            text=text,
            timestamp=now.isoformat(),
            metadata=metadata or {}
        )
        self._chunks.append(chunk)
        self._append_to_disk(chunk)
        return chunk

    def _append_to_disk(self, chunk: MemoryChunk) -> None:
        """Append single chunk to JSONL (atomic)"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": chunk.id,
                "text": chunk.text,
                "timestamp": chunk.timestamp,
                "metadata": chunk.metadata,
                "embedding": chunk.embedding,
            }, ensure_ascii=False) + "\n")

    def get_all(self) -> List[MemoryChunk]:
        return list(self._chunks)
