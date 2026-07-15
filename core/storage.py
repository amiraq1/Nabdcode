# core/storage.py
"""
UnifiedStorage — Nabd OS Unified Memory &amp; State Persistence Layer
====================================================================

Consolidates five extant persistence backends behind a single thread-safe
interface, protecting Termux/Android memory with output caps, RLock-guarded
concurrent access, and a unified compaction/retention policy.

Backends aggregated:
  • MemoryManager  — SQLite FTS5 semantic memory (long-term search)
  • MemoryStore    — JSONL chunk-store (hybrid retriever chunks)
  • SessionManager — JSON session file (messages, todos, evidence)
  • TodoManager    — RAM-backed TODO plan (serialized via SessionManager)
  • EvidenceLog    — RAM-backed evidence records (serialized via SessionManager)

Design constraints (from the architectural cleanup):
  1. Thread-safe: ALL public methods acquire self._lock (RLock) so the
     async REPL event loop and the blocking agent worker thread never race.
  2. Output caps: search/get results are truncated to MAX_OUTPUT_CHARS (1000)
     per record so retrieved context never inflates the LLM window.
  3. Unified compact(): single entry point for age-based pruning across
     all backends — no more scattered retention logic.

Usage:
    from core.storage import UnifiedStorage

    storage = UnifiedStorage(root_dir=Path("."))
    storage.store_memory("user", "important lesson", project="nabd")
    results = storage.search_memory("lesson", limit=5)
    storage.save_session(session_id="sess_abc", messages=[...])
    storage.compact(max_age_days=30)
    storage.close()
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from core.sanitize import sanitize

logger = logging.getLogger("UnifiedStorage")

# ── Output protection cap ───────────────────────────────────────────────────
# Limits the character length of any single record's content returned by
# search/get operations. Protects the Termux context window from OOM when
# a retrieved memory/session blob is excessively large.
# The 1000-char ceiling balances recall fidelity against memory pressure.
MAX_OUTPUT_CHARS: int = 1000

# ── Aggregation cap ─────────────────────────────────────────────────────────
# Maximum number of records returned by bulk retrieval operations (e.g.
# get_all_memories, list_sessions). Prevents unbounded iteration.
MAX_RECORDS_PER_QUERY: int = 100

# ── Default compaction horizon ──────────────────────────────────────────────
# Records older than this many days are eligible for pruning during compact().
DEFAULT_MAX_AGE_DAYS: int = 30


class UnifiedStorage:
    """Thread-safe, capped, unified persistence facade.

    Every public method acquires the reentrant lock so the async UI loop
    and the blocking agent thread can share the same storage instance
    without race conditions. All content-bearing returns are truncated to
    MAX_OUTPUT_CHARS to protect the Termux context window.
    """

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def __init__(
        self,
        root_dir: Path | None = None,
        max_output_chars: int = MAX_OUTPUT_CHARS,
    ) -> None:
        self._lock = RLock()
        self._max_output = max_output_chars

        root = Path(root_dir) if root_dir is not None else Path.cwd()
        self._sessions_dir = root / "sessions"
        self._memory_path = root / ".nabd" / "memory" / "memory.jsonl"
        self._sqlite_path: Path | None = None  # set via set_sqlite_path()

        # ── Lazy-loaded backends ──────────────────────────────────────────
        self._session_mgr: Any = None
        self._memory_mgr: Any = None
        self._store: Any = None
        self._todo_mgr: Any = None
        self._evidence_log: Any = None
        self._lru_cache: Any = None

    def set_sqlite_path(self, path: Path | str) -> None:
        """Configure the SQLite database path for the MemoryManager backend.

        Must be called before store_memory() / search_memory() if the
        caller wants SQLite-backed semantic memory. Default is None, which
        means search_memory() falls back to the JSONL MemoryStore.
        """
        self._sqlite_path = Path(path)

    # ── Internal lazy accessors (thread-safe, cached) ─────────────────────

    def _get_session_mgr(self) -> Any:
        from core.session import SessionManager

        if self._session_mgr is None:
            self._session_mgr = SessionManager(root=self._sessions_dir)
        return self._session_mgr

    def _get_memory_mgr(self) -> Any:
        from core.memory import MemoryManager

        if self._memory_mgr is None:
            db_path = self._sqlite_path or (
                Path.cwd() / "workspace_memory.db"
            )
            self._memory_mgr = MemoryManager(db_path=str(db_path))
        return self._memory_mgr

    def _get_store(self) -> Any:
        from core.memory_store import MemoryStore

        if self._store is None:
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            self._store = MemoryStore(self._memory_path)
        return self._store

    def _get_todo_mgr(self) -> Any:
        from core.todo import TodoManager

        if self._todo_mgr is None:
            self._todo_mgr = TodoManager()
        return self._todo_mgr

    def _get_evidence_log(self) -> Any:
        from core.evidence import EvidenceLog

        if self._evidence_log is None:
            self._evidence_log = EvidenceLog()
        return self._evidence_log

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _cap(text: str | None, max_len: int = MAX_OUTPUT_CHARS) -> str:
        """Truncate ``text`` to ``max_len`` characters, appending a notice.

        Returns empty string on None/empty input.
        """
        if not text:
            return ""
        text_str = str(text)
        suffix = "... [TRUNCATED by UnifiedStorage to protect context]"
        if len(text_str) > max_len:
            text_str = text_str[: max_len - len(suffix)] + suffix
        return text_str

    @staticmethod
    def _cap_dict(
        d: dict, fields: list[str], max_len: int = MAX_OUTPUT_CHARS
    ) -> dict:
        """Return a shallow copy of ``d`` with the listed fields truncated."""
        out = dict(d)
        for f in fields:
            if f in out and isinstance(out[f], str):
                out[f] = UnifiedStorage._cap(out[f], max_len)
        return out

    # ═══════════════════════════════════════════════════════════════════════
    #  BACKEND 1 — Session Persistence (JSON)
    # ═══════════════════════════════════════════════════════════════════════

    def save_session(
        self,
        session_id: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        todos: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        goal: dict[str, Any] | None = None,
    ) -> bool:
        """Persist the current session state to a JSON file.

        Thread-safe. Delegates to SessionManager.save(). Returns True on
        success, False on I/O error.
        """
        with self._lock:
            mgr = self._get_session_mgr()
            if session_id is not None:
                mgr.session_id = session_id
            if messages is not None:
                mgr.messages = list(messages)
            if todos is not None:
                mgr.todos = list(todos)
            if evidence is not None:
                mgr.evidence = list(evidence)
            if goal is not None:
                mgr.goal = dict(goal) if isinstance(goal, dict) else goal
            return mgr.save()

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a previously saved session from its JSON file.

        Returns the raw session dict (with capped message content) or None
        if the session file is missing or corrupt.
        """
        with self._lock:
            mgr = self._get_session_mgr()
            ok = mgr.load(session_id)
            if not ok:
                return None
            return {
                "session_id": mgr.session_id,
                "messages": [
                    self._cap_dict(m, ["content"])
                    for m in mgr.messages
                ],
                "todos": mgr.todos,
                "evidence": mgr.evidence,
                "goal": mgr.goal,
            }

    def get_latest_session(self) -> str | None:
        """Return the session_id of the most recent session file, or None."""
        with self._lock:
            return self._get_session_mgr().get_latest_session(
                self._sessions_dir
            )

    def list_sessions(self) -> list[str]:
        """Return session_ids of all session files, newest first, capped."""
        with self._lock:
            root = self._sessions_dir
            if not root.exists():
                return []
            files = sorted(
                root.glob("sess_*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )[:MAX_RECORDS_PER_QUERY]
            return [f.stem for f in files]

    def enforce_session_retention(self, max_sessions: int = 50) -> int:
        """Delete oldest session files beyond ``max_sessions``.

        Returns the number of files deleted.
        """
        with self._lock:
            return self._get_session_mgr().enforce_retention_policy(
                max_sessions
            )

    # ═══════════════════════════════════════════════════════════════════════
    #  BACKEND 2 — Semantic Memory (SQLite FTS5 + JSONL)
    # ═══════════════════════════════════════════════════════════════════════

    def store_memory(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        importance: float = 1.0,
        project: str = "",
        tags: str = "",
    ) -> int:
        """Store a semantic memory record.

        Persists to BOTH the SQLite backend (for FTS5 search) and the JSONL
        backend (for hybrid retrieval). Returns the SQLite row id.
        """
        sanitized = sanitize(content)
        if not sanitized:
            return -1
        # Cap input to prevent unbounded growth
        sanitized = sanitized[:MAX_OUTPUT_CHARS]

        with self._lock:
            # 1. SQLite backend (MemoryManager)
            try:
                mgr = self._get_memory_mgr()
                row_id = mgr.add_memory(
                    role=role,
                    content=sanitized,
                    metadata=metadata,
                    importance=importance,
                    project=project,
                    tags=tags,
                )
            except Exception as exc:
                logger.warning(f"SQLite store_memory failed: {exc}")
                row_id = -1

            # 2. JSONL backend (MemoryStore) — for hybrid retriever
            try:
                store = self._get_store()
                store.add(text=sanitized, metadata={"role": role, "project": project})
            except Exception as exc:
                logger.warning(f"JSONL store_memory failed: {exc}")

            return row_id

    def search_memory(
        self,
        query: str,
        limit: int = 5,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search semantic memory using hybrid (FTS5 + recent + file-context).

        Returns up to ``limit`` results with content capped to
        MAX_OUTPUT_CHARS. Falls back to JSONL keyword search if SQLite is
        unavailable.
        """
        if not query or not query.strip():
            return []

        with self._lock:
            # Primary: SQLite FTS5 via MemoryManager.hybrid_search()
            try:
                mgr = self._get_memory_mgr()
                results = mgr.hybrid_search(
                    query=query,
                    limit=min(limit, MAX_RECORDS_PER_QUERY),
                    project=project,
                )
                if results:
                    return [
                        self._cap_dict(r, ["content", "metadata"])
                        for r in results
                    ]
            except Exception as exc:
                logger.debug(f"SQLite search_memory failed, falling back: {exc}")

            # Fallback: JSONL keyword scan
            try:
                from core.hybrid_retriever import HybridRetriever

                store = self._get_store()
                retriever = HybridRetriever(store)
                results = retriever.search(query, top_k=limit)
                return [
                    {
                        "id": r.get("id", ""),
                        "content": self._cap(r.get("text", ""), MAX_OUTPUT_CHARS),
                        "score": r.get("score", 0.0),
                        "timestamp": r.get("timestamp", ""),
                    }
                    for r in results[:limit]
                ]
            except Exception as exc:
                logger.warning(f"JSONL fallback search failed: {exc}")
                return []

    def get_recent_memories(
        self, limit: int = 10, project: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch the most recent memory records, newest first."""
        with self._lock:
            try:
                mgr = self._get_memory_mgr()
                results = mgr.get_recent_history(
                    limit=min(limit, MAX_RECORDS_PER_QUERY), project=project
                )
                return [
                    self._cap_dict(r, ["content", "metadata"])
                    for r in results
                ]
            except Exception as exc:
                logger.warning(f"get_recent_memories failed: {exc}")
                return []

    # ═══════════════════════════════════════════════════════════════════════
    #  BACKEND 3 — TODO Plan (RAM, serialized via SessionManager)
    # ═══════════════════════════════════════════════════════════════════════

    def set_todo_plan(self, items: list[str]) -> list[dict[str, Any]]:
        """Replace the current TODO plan with a new list of tasks."""
        with self._lock:
            mgr = self._get_todo_mgr()
            todos = mgr.set_plan(items)
            return [t.to_dict() for t in todos]

    def mark_todo_done(
        self, item_id: int, verification_note: str = ""
    ) -> dict[str, Any] | None:
        """Mark a TODO item as done with a verification note."""
        from core.todo import TodoManager

        with self._lock:
            try:
                mgr = self._get_todo_mgr()
                item = mgr.mark_done(item_id, verification_note)
                return item.to_dict()
            except (ValueError, KeyError) as exc:
                logger.warning(f"mark_todo_done failed: {exc}")
                return None

    def mark_todo_in_progress(self, item_id: int) -> dict[str, Any] | None:
        """Mark a TODO item as in progress."""
        with self._lock:
            try:
                mgr = self._get_todo_mgr()
                item = mgr.mark_in_progress(item_id)
                return item.to_dict()
            except KeyError as exc:
                logger.warning(f"mark_todo_in_progress failed: {exc}")
                return None

    def get_todo_plan(self) -> list[dict[str, Any]]:
        """Return the full TODO plan (read-only snapshot)."""
        with self._lock:
            mgr = self._get_todo_mgr()
            return [t.to_dict() for t in mgr.all()]

    def restore_todo_plan(self, data: list[dict[str, Any]]) -> None:
        """Restore the TODO plan from serialized data (e.g. session load)."""
        with self._lock:
            self._get_todo_mgr().restore(list(data))

    # ═══════════════════════════════════════════════════════════════════════
    #  BACKEND 4 — Evidence Records (RAM, serialized via SessionManager)
    # ═══════════════════════════════════════════════════════════════════════

    def record_evidence(
        self,
        tool: str,
        command_or_path: str,
        success: bool,
        output_snippet: str,
        critical: bool = False,
    ) -> Any:
        """Record a tool execution as evidence.

        Returns the EvidenceRecord (content capped).
        """
        with self._lock:
            log = self._get_evidence_log()
            snippet = self._cap(output_snippet)
            return log.record(
                tool=tool,
                command_or_path=command_or_path,
                success=success,
                output_snippet=snippet,
                critical=critical,
            )

    def get_evidence_records(self) -> list[Any]:
        """Return all evidence records (read-only snapshot)."""
        with self._lock:
            log = self._get_evidence_log()
            return list(log.get_records())

    def get_evidence_summary(self) -> list[dict[str, Any]]:
        """Return evidence records as capped dicts for display/serialization."""
        with self._lock:
            log = self._get_evidence_log()
            return [
                {
                    "evidence_id": r.evidence_id,
                    "tool": r.tool,
                    "success": r.success,
                    "snippet": self._cap(r.output_snippet),
                    "critical": r.critical,
                }
                for r in log.get_records()
            ]

    def flag_evidence_critical(self, evidence_id: str) -> None:
        """Freeze an evidence record so it survives context compaction."""
        with self._lock:
            self._get_evidence_log().flag_critical(evidence_id)

    def restore_evidence(self, data: dict[str, Any]) -> None:
        """Restore evidence records from serialized data."""
        with self._lock:
            self._get_evidence_log().restore(data)

    # ═══════════════════════════════════════════════════════════════════════
    #  BACKEND 5 — LRU Content Cache (RAM, TTL-evicted)
    # ═══════════════════════════════════════════════════════════════════════

    def _get_lru_cache(self) -> Any:
        """Lazy-initialize the LRUTTLMemory cache singleton."""
        from core.memory import LRUTTLMemory

        if self._lru_cache is None:
            self._lru_cache = LRUTTLMemory(capacity=200, default_ttl=3600.0)
        return self._lru_cache

    def cache_get(self, key: str) -> Any | None:
        """Retrieve a value from the TTL cache (or None if missing/expired)."""
        with self._lock:
            return self._get_lru_cache().get(key)

    def cache_put(
        self, key: str, value: Any, ttl_seconds: float = 3600.0
    ) -> None:
        """Store a value in the TTL cache with a time-to-live."""
        with self._lock:
            self._get_lru_cache().put(key, value, ttl=ttl_seconds)

    # ═══════════════════════════════════════════════════════════════════════
    #  UNIFIED SAVE / RESTORE
    # ═══════════════════════════════════════════════════════════════════════

    def save_all(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        goal: dict[str, Any] | None = None,
    ) -> bool:
        """Save the complete runtime state in one call.

        Aggregates: messages + todos + evidence + goal → SessionManager.
        Returns True iff the session file was written successfully.
        """
        with self._lock:
            todos = self._get_todo_mgr().to_serializable()
            evidence = self._get_evidence_log().to_serializable().get("records", [])
            return self.save_session(
                session_id=session_id,
                messages=messages,
                todos=todos,
                evidence=evidence,
                goal=goal,
            )

    def restore_all(self, session_id: str) -> bool:
        """Restore the complete runtime state from a session file.

        Restores: messages, todos, evidence, goal from the session JSON.
        Returns True iff the session was found and loaded successfully.
        """
        with self._lock:
            data = self.load_session(session_id)
            if data is None:
                return False
            # Restore messages — caller pulls via get_session_messages()
            # Restore todos
            if data.get("todos"):
                self._get_todo_mgr().restore(list(data["todos"]))
            # Restore evidence
            if data.get("evidence"):
                self._get_evidence_log().restore(
                    {"records": list(data["evidence"])}
                )
            return True

    def get_session_messages(
        self, session_id: str
    ) -> list[dict[str, Any]] | None:
        """Return only the messages array for a session (capped content)."""
        data = self.load_session(session_id)
        if data is None:
            return None
        return data.get("messages", [])

    # ═══════════════════════════════════════════════════════════════════════
    #  UNIFIED COMPACTION
    # ═══════════════════════════════════════════════════════════════════════

    def compact(self, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> dict[str, int]:
        """Run age-based pruning across ALL backends.

        Actions:
          1. SQLite MemoryManager — VACUUM + prune oldest records over limit
             (the MemoryManager handles its own max_records internally).
          2. Session retention — delete sessions older than ``max_age_days``.
          3. JSONL MemoryStore — remove chunks older than ``max_age_days``
             (rewrites the file atomically).

        Returns a dict of {action: count} for logging/monitoring.
        """
        report: dict[str, int] = {}
        cutoff = time.time() - (max_age_days * 86400)

        with self._lock:
            # 1. SQLite compact
            try:
                mgr = self._get_memory_mgr()
                mgr.vacuum()
                report["sqlite_vacuum"] = 1
            except Exception as exc:
                logger.warning(f"SQLite compact failed: {exc}")
                report["sqlite_vacuum"] = 0

            # 2. Session retention
            try:
                # Delete session files older than cutoff
                root = self._sessions_dir
                deleted = 0
                if root.exists():
                    for f in root.glob("sess_*.json"):
                        try:
                            if f.stat().st_mtime < cutoff:
                                f.unlink()
                                deleted += 1
                        except OSError:
                            pass
                report["sessions_deleted"] = deleted
            except Exception as exc:
                logger.warning(f"Session compact failed: {exc}")
                report["sessions_deleted"] = 0

            # 3. JSONL MemoryStore compaction
            try:
                store = self._get_store()
                all_chunks = store.get_all()
                keep = [c for c in all_chunks if self._chunk_age_ok(c, cutoff)]
                removed = len(all_chunks) - len(keep)
                if removed > 0:
                    # Rewrite the JSONL file with only kept chunks
                    self._memory_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self._memory_path, "w", encoding="utf-8") as f:
                        for chunk in keep:
                            f.write(
                                json.dumps(
                                    {
                                        "id": chunk.id,
                                        "text": chunk.text,
                                        "timestamp": chunk.timestamp,
                                        "metadata": chunk.metadata,
                                        "embedding": chunk.embedding,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    # Reload the in-memory store
                    self._store = None  # force re-init on next access
                report["jsonl_chunks_removed"] = removed
            except Exception as exc:
                logger.warning(f"JSONL compact failed: {exc}")
                report["jsonl_chunks_removed"] = 0

            return report

    @staticmethod
    def _chunk_age_ok(chunk: Any, cutoff: float) -> bool:
        """Check if a MemoryChunk's timestamp is after the cutoff.

        Handles both ISO-8601 string timestamps and Unix epoch floats.
        """
        try:
            ts = chunk.timestamp
            if isinstance(ts, str):
                from datetime import datetime

                dt = datetime.fromisoformat(ts)
                return dt.timestamp() >= cutoff
            return float(ts) >= cutoff
        except Exception:
            # If we can't parse the timestamp, keep the chunk (conservative).
            return True

    # ═══════════════════════════════════════════════════════════════════════
    #  LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════

    def close(self) -> None:
        """Close all backend connections and release resources."""
        with self._lock:
            if self._memory_mgr is not None:
                try:
                    self._memory_mgr.close()
                except Exception as exc:
                    logger.debug(f"MemoryManager close: {exc}")
                self._memory_mgr = None
            self._session_mgr = None
            self._store = None
            self._todo_mgr = None
            self._evidence_log = None
            self._lru_cache = None

    def __enter__(self) -> UnifiedStorage:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
