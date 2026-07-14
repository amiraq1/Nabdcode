import hashlib
import json
import logging
import math
import sqlite3
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from core.sanitize import sanitize


class LRUTTLMemory:
    """
    LRU cache with TTL (time-to-live) eviction.
    """

    def __init__(self, capacity: int = 100, default_ttl: float = 3600.0):
        self.capacity = capacity
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
        value, expiry = self._cache[key]
        if time.time() > expiry:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def put(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if ttl is None:
            ttl = self.default_ttl
        expiry = time.time() + ttl

        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self.capacity:
            self._remove_oldest_or_expired()
            if len(self._cache) >= self.capacity:
                self._cache.popitem(last=False)

        self._cache[key] = (value, expiry)

    def _remove_oldest_or_expired(self):
        now = time.time()
        expired_keys = [k for k, (_, exp) in self._cache.items() if now > exp]
        for k in expired_keys:
            del self._cache[k]

    def clear(self):
        self._cache.clear()


class MemoryManager:
    """
    Semantic memory manager for the Nabd Agent OS.
    Uses SQLite FTS5 for fast text/code search with WAL mode, concurrency, size management, and hybrid search.
    """

    def __init__(self, db_path: str = "workspace_memory.db", max_records: int = 100000):
        self.db_path = Path(db_path)
        self.max_records = max_records
        self.lock = RLock()
        self.deleted_counter = 0

        # 1. Persistent connection pool (thread-safe)
        # Retry with corruption recovery
        self.conn = None
        try:
            self.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            self.conn.row_factory = sqlite3.Row
            self._init_db()
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
            # Corruption recovery: rename corrupt DB, recreate from scratch
            corrupt_path = self.db_path.with_suffix(".db.corrupt")
            import warnings
            warnings.warn(
                f"Database corruption detected at {self.db_path}: {exc}. "
                f"Renaming to {corrupt_path} and recreating."
            )
            if self.db_path.exists():
                self.db_path.rename(corrupt_path)
            # Also clean up WAL/SHM files
            for suffix in ("-wal", "-shm"):
                extra = self.db_path.with_name(self.db_path.name + suffix)
                if extra.exists():
                    extra.unlink(missing_ok=True)
            self.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            self.conn.row_factory = sqlite3.Row
            self._init_db()

    def _init_db(self):
        """Initialize database with WAL, tables, indexes, and triggers for auto-sync."""
        with self.lock:
            cursor = self.conn.cursor()

            # 2. Enable WAL and pragmas for Termux performance
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-20000")
            cursor.execute("PRAGMA foreign_keys=ON")

            # 10. Memory table with support for embeddings, importance, projects, and tags
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    timestamp REAL NOT NULL,
                    embedding_id INTEGER,
                    importance REAL DEFAULT 1.0,
                    project TEXT DEFAULT '',
                    tags TEXT DEFAULT ''
                )
            """)

            # 3. Create indexes for fast search and sorting
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON memory_logs(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_role ON memory_logs(role)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_project ON memory_logs(project)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags ON memory_logs(tags)")

            # 4. FTS5 virtual table with external content linked to main table
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(
                    content,
                    role,
                    metadata,
                    project,
                    tags,
                    content='memory_logs',
                    content_rowid='id'
                )
            """)

            # 4. Triggers for bi-directional sync (Insert / Delete / Update)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_logs_ai AFTER INSERT ON memory_logs BEGIN
                    INSERT INTO memory_search(rowid, content, role, metadata, project, tags)
                    VALUES (new.id, new.content, new.role, new.metadata, new.project, new.tags);
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_logs_ad AFTER DELETE ON memory_logs BEGIN
                    INSERT INTO memory_search(memory_search, rowid, content, role, metadata, project, tags)
                    VALUES('delete', old.id, old.content, old.role, old.metadata, old.project, old.tags);
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_logs_au AFTER UPDATE ON memory_logs BEGIN
                    INSERT INTO memory_search(memory_search, rowid, content, role, metadata, project, tags)
                    VALUES('delete', old.id, old.content, old.role, old.metadata, old.project, old.tags);
                    INSERT INTO memory_search(rowid, content, role, metadata, project, tags)
                    VALUES (new.id, new.content, new.role, new.metadata, new.project, new.tags);
                END;
            """)

    def add_memory(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 1.0,
        project: str = "",
        tags: str = "",
        embedding_id: Optional[int] = None,
    ) -> int:
        """
        Save a new memory record with concurrency protection and auto-size management (Pruning & Vacuum).
        """
        meta_str = json.dumps(metadata) if metadata else "{}"
        current_time = time.time()

        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO memory_logs (role, content, metadata, timestamp, importance, project, tags, embedding_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (role, content, meta_str, current_time, importance, project, tags, embedding_id),
            )
            row_id = cursor.lastrowid

            # 7. Size management: delete oldest records if limit exceeded
            self._prune_if_needed(cursor)

            return row_id

    def _prune_if_needed(self, cursor: sqlite3.Cursor):
        cursor.execute("SELECT count(*) FROM memory_logs")
        count = cursor.fetchone()[0]
        if count > self.max_records:
            target_size = max(1, int(self.max_records * 0.9))
            excess = count - target_size
            cursor.execute(
                """
                DELETE FROM memory_logs
                WHERE id IN (
                    SELECT id
                    FROM memory_logs
                    ORDER BY timestamp ASC
                    LIMIT ?
                )
                """,
                (excess,),
            )
            self.deleted_counter += cursor.rowcount

            # 8. Auto-vacuum when deletes accumulate
            if self.deleted_counter >= 1000:
                self.vacuum()
                self.deleted_counter = 0

    def vacuum(self):
        """Vacuum and compress database to free space."""
        with self.lock:
            self.conn.execute("VACUUM")

    def search_context(self, query: str, limit: int = 5, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fast FTS5 search with parameterized query protection.
        """
        words = [w for w in query.replace('"', '').replace("'", '').replace('*', '').split() if w]
        if not words:
            return []

        # 5. Protect FTS queries from injection
        fts_query = " ".join(f'"{w}"*' for w in words)

        with self.lock:
            cursor = self.conn.cursor()
            sql = """
                SELECT m.*
                FROM memory_search s
                JOIN memory_logs m ON s.rowid = m.id
                WHERE memory_search MATCH ?
            """
            params: list[Any] = [fts_query]

            if project:
                sql += " AND m.project = ?"
                params.append(project)

            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            try:
                cursor.execute(sql, tuple(params))
            except sqlite3.OperationalError:
                return []

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_dict(row))
            return results

    def get_recent_history(self, limit: int = 10, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch recent conversation history to restore short-term memory on restart."""
        with self.lock:
            cursor = self.conn.cursor()
            if project:
                cursor.execute(
                    "SELECT * FROM memory_logs WHERE project = ? ORDER BY timestamp DESC LIMIT ?",
                    (project, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM memory_logs ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()[::-1]
            return [self._row_to_dict(row) for row in rows]

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        project: Optional[str] = None,
        current_file: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        9. Hybrid search combining FTS5 full-text, recent history, and project/file-context with importance-weighted ranking.
        """
        results_map: Dict[int, Dict[str, Any]] = {}
        scores_map: Dict[int, float] = {}

        # 1. FTS5 full-text search
        fts_results = self.search_context(query, limit=limit * 2, project=project)
        for idx, item in enumerate(fts_results):
            r_id = item["id"]
            results_map[r_id] = item
            # Initial score decreasing by rank, boosted by importance
            scores_map[r_id] = scores_map.get(r_id, 0.0) + (limit * 2 - idx) * float(item.get("importance", 1.0))

        # 2. Recent conversation history
        recent_results = self.get_recent_history(limit=limit, project=project)
        for idx, item in enumerate(recent_results):
            r_id = item["id"]
            results_map[r_id] = item
            scores_map[r_id] = scores_map.get(r_id, 0.0) + (idx + 1) * 0.5 * float(item.get("importance", 1.0))

        # 3. Boost memories related to the current file
        if current_file:
            escaped_file = current_file.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            with self.lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    "SELECT * FROM memory_logs WHERE content LIKE ? ESCAPE '\\' OR metadata LIKE ? ESCAPE '\\' ORDER BY timestamp DESC LIMIT ?",
                    (f"%{escaped_file}%", f"%{escaped_file}%", limit),
                )
                for row in cursor.fetchall():
                    item = self._row_to_dict(row)
                    r_id = item["id"]
                    results_map[r_id] = item
                    scores_map[r_id] = scores_map.get(r_id, 0.0) + limit * 1.5 * float(item.get("importance", 1.0))

        # Sort merged results by total hybrid score
        sorted_ids = sorted(scores_map.keys(), key=lambda k: scores_map[k], reverse=True)
        return [results_map[r_id] for r_id in sorted_ids[:limit]]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        keys = row.keys()
        meta_raw = row["metadata"] if "metadata" in keys else "{}"
        try:
            metadata = json.loads(meta_raw) if meta_raw else {}
        except Exception:
            metadata = {}
        return {
            "id": row["id"] if "id" in keys else None,
            "role": row["role"] if "role" in keys else "",
            "content": row["content"] if "content" in keys else "",
            "metadata": metadata,
            "timestamp": row["timestamp"] if "timestamp" in keys else 0.0,
            "importance": row["importance"] if "importance" in keys else 1.0,
            "project": row["project"] if "project" in keys else "",
            "tags": row["tags"] if "tags" in keys else "",
            "embedding_id": row["embedding_id"] if "embedding_id" in keys else None,
        }

    def close(self):
        """Close the database connection safely."""
        with self.lock:
            if self.conn:
                self.conn.close()
                self.conn = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


MEMORY_FILE = Path("MEMORY.md")
MAX_MEMORY_CHARS = 4000  # لمنع انفجار السياق، نفس فكرة Compaction


def load_memory() -> str:
    if not MEMORY_FILE.exists():
        return ""
    text = MEMORY_FILE.read_text(encoding="utf-8")
    return text[-MAX_MEMORY_CHARS:]


def write_lesson(problem: str, solution: str):
    entry = f"\n## {datetime.now().date()} - درس مستفاد\n"
    entry += f"**المشكلة:** {problem}\n"
    entry += f"**الحل:** {solution}\n"

    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


logger = logging.getLogger("SemanticMemory")


class PurePythonEmbedder:
    """
    Termux-friendly lightweight vector embedder using deterministic token and character n-gram hashing.
    Requires zero external C++ build dependencies while providing robust semantic similarity.
    """

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        cleaned = sanitize(text, strip_ansi=True).lower()
        vec = [0.0] * self.dim
        if not cleaned:
            return vec

        words = [w for w in cleaned.replace('"', " ").replace("'", " ").split() if len(w) > 1]
        for w in words:
            h = int.from_bytes(hashlib.md5(w.encode("utf-8")).digest()[:4], "big") % self.dim
            vec[h] += 1.0

            for i in range(len(w) - 1):
                bg = w[i : i + 2]
                h2 = int.from_bytes(hashlib.md5(bg.encode("utf-8")).digest()[:4], "big") % self.dim
                vec[h2] += 0.5

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        return sum(a * b for a, b in zip(v1, v2))


class SemanticMemoryPipeline:
    """
    Zero-Trust Semantic Memory Pipeline for Nabd Agent OS.
    Implements:
      1. Lightweight deterministic vector storage and cosine similarity ranking.
      2. Context stuffing prevention via strict context size caps.
      3. Automatic output sanitization through core.sanitize.
    """

    def __init__(
        self,
        store_path: str = "workspace_semantic_memory.json",
        max_records: int = 5000,
        max_context_chars: int = 3000,
    ) -> None:
        self.store_path = Path(store_path)
        self.max_records = max_records
        self.max_context_chars = max_context_chars
        self.embedder = PurePythonEmbedder(dim=128)
        self.lock = RLock()
        self._records: List[Dict[str, Any]] = []
        self._load_store()

    def _load_store(self) -> None:
        with self.lock:
            if self.store_path.exists():
                try:
                    data = json.loads(self.store_path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        self._records = data
                except Exception as exc:
                    logger.warning(f"Failed to load semantic memory store: {exc}")
                    self._records = []

    def _save_store(self) -> None:
        with self.lock:
            if len(self._records) > self.max_records:
                # Keep most recent max_records
                self._records = self._records[-self.max_records :]
            try:
                self.store_path.write_text(
                    json.dumps(self._records, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.error(f"Failed to save semantic memory store: {exc}")

    def add_memory(
        self,
        content: str,
        role: str = "agent",
        project: str = "",
        importance: float = 1.0,
        tags: Optional[List[str]] = None,
    ) -> int:
        clean_content = sanitize(content)
        if not clean_content.strip():
            return -1

        embedding = self.embedder.embed(clean_content)
        record = {
            "id": int(time.time() * 1000),
            "role": role,
            "content": clean_content,
            "project": project,
            "importance": float(importance),
            "tags": tags or [],
            "timestamp": time.time(),
            "embedding": embedding,
        }

        with self.lock:
            self._records.append(record)
            self._save_store()

        logger.info(f"Stored semantic memory id={record['id']} (len={len(clean_content)})")
        return record["id"]

    def search_memory(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.1,
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clean_query = sanitize(query)
        if not clean_query.strip():
            return []

        query_vec = self.embedder.embed(clean_query)

        scored: List[Tuple[float, Dict[str, Any]]] = []
        with self.lock:
            for rec in self._records:
                if project and rec.get("project") and rec.get("project") != project:
                    continue

                sim = PurePythonEmbedder.cosine_similarity(query_vec, rec.get("embedding", []))
                weighted_score = sim * float(rec.get("importance", 1.0))
                if weighted_score >= min_similarity:
                    scored.append((weighted_score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Context Stuffing Prevention: enforce surgical max_context_chars cap
        results: List[Dict[str, Any]] = []
        accumulated_chars = 0

        for score, rec in scored:
            clean_rec_content = sanitize(rec.get("content", ""))
            content_len = len(clean_rec_content)

            if accumulated_chars + content_len > self.max_context_chars and results:
                logger.info(
                    "Context Stuffing Prevention triggered: truncating search results at max_context_chars cap"
                )
                break

            rec_copy = dict(rec)
            rec_copy["content"] = clean_rec_content
            rec_copy["similarity_score"] = round(score, 4)
            rec_copy.pop("embedding", None)  # Don't return raw embedding vector in output

            results.append(rec_copy)
            accumulated_chars += content_len
            if len(results) >= top_k:
                break

        return results

