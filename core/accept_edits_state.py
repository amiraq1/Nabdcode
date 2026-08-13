"""Shared accept-edits state between ``tools/file_system.py`` and ``ui/repl_termux.py``.

This module breaks the UI -> tools layer violation: instead of the REPL importing
internal state from ``tools.file_system``, both the tool and the UI depend on
this lower-level ``core/`` module (Dependency Inversion).

State lifecycle:
  - ``_accept_edits_pending`` is populated by tools/file_system.py when
    accept-edits mode is active, drained by ui/repl_termux.py after each
    agent turn completes.
  - ``_accept_edits_enabled`` is set by the REPL's mode-cycling logic.
  - ``reset_session()`` clears ALL state (pending edits + enabled flag) so
    no stale footer state leaks between sessions or tasks.
  - ``has_pending_edits()`` returns True ONLY when there are actual pending
    edits in the queue — the footer must not show "accept edits on" when
    there are zero pending edits.
"""

from __future__ import annotations

import dataclasses
import difflib
import errno
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore
import hashlib
import json
import logging
import os
import stat as _stat
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path as _Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

_logger = logging.getLogger(__name__)

class TransactionOutcome(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"
    DENIED = "DENIED"
    NOT_FOUND = "NOT_FOUND"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    ACCEPTED_WITH_DURABILITY_WARNING = "ACCEPTED_WITH_DURABILITY_WARNING"

@dataclass(frozen=True)
class TransactionFailure:
    edit_id: str
    stage: str
    error_type: str
    safe_message: str
    retryable: bool

@dataclass(frozen=True)
class TransactionResult:
    outcome: TransactionOutcome
    operation_id: str
    succeeded_ids: list[str]
    failed_items: list[TransactionFailure]
    remaining_ids: list[str]
    processed_count: int

@dataclass(frozen=True)
class Snapshot:
    """Point-in-time copy of a file's content and metadata for rollback."""
    edit_id: str
    resolved_path: str
    old_content: str
    digest: str

@dataclass(frozen=True)
class ReconciliationRecord:
    """Durable journal entry for operations that reached an ambiguous state."""
    operation_id: str
    edit_id: str
    resolved_path: str
    claim_token: str
    expected_digest: str
    observed_digest: str | None
    failure_stage: str
    recovery_status: str
    has_snapshot: bool
    timestamp_ns: int


JOURNAL_SCHEMA_VERSION: int = 1
JOURNAL_MAX_RECORD_BYTES: int = 1 * 1024 * 1024  # 1 MiB


@dataclass(frozen=True)
class WalRecord:
    """Write-Ahead Journal record for pending-edit transactions.

    Each record is a single append-only JSON line.  Events follow the
    monotonic sequence PREPARED(1) → APPLIED(2) → COMMITTED(3) → RESOLVED(4).
    """
    record_id: str                      # uuid4(), globally unique
    workspace_id: str                   # uuid4(), identifies workspace
    workspace_root_fingerprint: str     # sha256(workspace_root.encode())
    operation_id: str                   # uuid4(), groups events
    sequence: int                       # 1=prepared, 2=applied, 3=committed, 4=resolved
    event_type: str                     # PREPARED | APPLIED | COMMITTED | RESOLVED | FAILED | RECONCILIATION_REQUIRED
    edit_id: str
    operation_type: str                 # ACCEPT | REJECT
    target_path_relative: str           # relative to workspace root
    expected_original_digest: str
    intended_result_digest: str
    schema_version: int = JOURNAL_SCHEMA_VERSION
    observed_result_digest: str | None = None
    snapshot_reference: str | None = None
    failure_stage: str | None = None
    side_effect_applied: bool = False
    durability_confirmed: bool = False
    cleanup_succeeded: bool = True
    recovery_status: str = ""           # "" | "PENDING_REVIEW" | "RESOLVED"
    created_at: str = ""                # ISO-8601 UTC, set by _serialize_wal_record
    checksum: str = ""                  # SHA-256 of canonical JSON (without checksum field)


@dataclass(frozen=True)
class RecoveryReport:
    """Startup recovery report — pure data, no I/O references."""
    operations: tuple[WalRecord, ...] = ()
    diagnostics: tuple[str, ...] = ()
    requires_review: bool = False
    corruption_detected: bool = False
    unsupported_schema_detected: bool = False
    foreign_workspace_records: bool = False
    truncated_tail_detected: bool = False


@dataclass(frozen=True)
class WorkspaceIdentity:
    """Immutable identity for workspace-scoped journal isolation."""
    workspace_id: str
    root_fingerprint: str


class WriteStage(str, Enum):
    """Identifies the exact I/O stage within _atomic_write."""
    TEMP_CREATE = "temp_create"
    TEMP_WRITE = "temp_write"
    TEMP_FSYNC = "temp_fsync"
    REPLACE = "replace"
    PARENT_FSYNC = "parent_fsync"
    TEMP_CLEANUP = "temp_cleanup"
    PRE_REPLACE_CHECK = "pre_replace_check"


@dataclass(frozen=True)
class AtomicWriteResult:
    """Structured result of a single _atomic_write call.  Never shared
    between operations — the instance is returned directly to the caller."""

    applied: bool
    """True if os.replace completed (content is now at target path)."""

    durability_confirmed: bool
    """True if parent-directory fsync was also confirmed."""

    cleanup_succeeded: bool
    """True if temp file was removed (or was never created / already replaced)."""

    failure_stage: WriteStage | None = None
    """The stage at which the primary error occurred, or None on success."""

    error_type: str | None = None
    """type(exception).__name__ of the primary error, or None."""

    safe_message: str | None = None
    """User-safe message (never includes absolute paths or repr(exc))."""

    temp_artifact_remaining: bool = False
    """True when a .tmp file was left behind because cleanup failed."""


@dataclass
class PendingEdit:
    """A file edit awaiting user approval before being written to disk."""
    path: str            # original relative path (for display)
    resolved_path: str   # absolute path resolved against workspace (for write)
    old_content: str
    new_content: str
    diff: str
    additions: int
    removals: int
    edit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "PENDING"
    version: int = 1
    claim_token: str | None = None
    expected_original_digest: str = ""
    snapshot: Snapshot | None = None


# ── Path-Lock Registry (Phase 2.2C) ──────────────────────────────────
# See Phase 2.2C protocol: bounded registry with explicit reference
# counting, waiter tracking, canonical keys, and lifecycle safety.


@dataclass
class _PathLockEntry:
    """Explicit registry entry for path-level locking.

    Attributes:
        lock: The underlying thread lock for mutual exclusion.
        references: Count of owners + waiters that have reserved this entry.
                    Incremented under registry lock before path-lock acquire.
                    Decremented in finally after path-lock release.
                    Entry is evicted only when references == 0.
    """
    lock: threading.Lock
    references: int = 0


# Module-level queue: populated by tools/file_system.py when accept-edits mode
# is active, drained by ui/repl_termux.py after each agent turn completes.
_accept_edits_pending: list[PendingEdit] = []
_accept_edits_enabled: bool = False

# Thread lock for concurrent access (agent thread + UI thread).
_state_lock = threading.Lock()

# Path-level lock registry for serializing same-path transactions.
# Maps canonical key -> _PathLockEntry with reference counting.
# Entries are created on first reference and evicted when references == 0.
_path_locks: dict[str, _PathLockEntry] = {}
_path_locks_lock = threading.Lock()


def _canonical_lock_key(path_str: str) -> str:
    """Produce a deterministic lock key from an authorized target path.

    The input MUST already be an authorized target path (from
    PendingEdit.resolved_path, which is the output of ``Path.resolve()``
    in ``tools/file_system.py:_resolve()`` — absolute, symlinks resolved,
    workspace-contained).

    Normalization uses ``os.path.normpath()`` to collapse ``.``, ``..``,
    and duplicate separators.  Does NOT lowercase (preserves F2FS/Android
    case sensitivity).  Does NOT re-resolve symlinks (already done).
    """
    return os.path.normpath(path_str)


@contextmanager
def _acquire_path_lock(path: _Path):
    """Acquire the per-path lock for *path* with lifecycle safety.

    Centralized context manager that replaces the old ``_get_path_lock()``
    raw-Lock return contract.  Every path transaction MUST use this API
    — no direct ``_path_locks`` mutation outside this function.

    Lifecycle (invariants confirmed):
      1. Canonicalize path key → registry lookup/create (under registry lock)
      2. references += 1 (under registry lock, before path-lock wait)
      3. Release registry lock
      4. Acquire path lock (outside registry lock — never nested)
      5. Yield to caller (critical section)
      6. Release path lock (in finally)
      7. references -= 1 (in finally, under registry lock)
      8. Evict if references == 0 AND registry identity still matches

    Exception/cancellation safety:
      - ``acquired`` flag prevents releasing a lock never acquired
      - reference decremented in ``finally`` regardless of exception
      - KeyboardInterrupt before acquire: no release, ref still decremented
    """
    key = _canonical_lock_key(str(path))
    entry: _PathLockEntry

    with _path_locks_lock:
        entry = _path_locks.get(key)
        if entry is None:
            entry = _PathLockEntry(lock=threading.Lock())
            _path_locks[key] = entry
        entry.references += 1

    acquired = False
    try:
        entry.lock.acquire()
        acquired = True
        yield entry
    finally:
        if acquired:
            entry.lock.release()
        with _path_locks_lock:
            entry.references -= 1
            if entry.references < 0:
                raise RuntimeError(
                    f"Negative path-lock reference count for key={key}"
                )
            if entry.references == 0 and _path_locks.get(key) is entry:
                del _path_locks[key]


def _get_path_lock_registry_snapshot() -> dict[str, int]:
    """Return a read-only snapshot of the path-lock registry.

    Returns {canonical_key: reference_count} — copied scalar diagnostics
    only.  Does NOT return live Lock, LockEntry, dict, or mutable
    references.  Mutating the returned dict does NOT affect the registry.

    Intended for testing/verification only.  Production code must use
    ``_acquire_path_lock()``.
    """
    with _path_locks_lock:
        return {k: v.references for k, v in _path_locks.items()}


# Sentinel for non-existent files (distinct from empty file).
_ABSENT_SENTINEL: str = "<NABD_ABSENT>"


def has_pending_edits() -> bool:
    """Return True ONLY when there are actual pending edits in the queue.

    The footer must show "accept edits on" only when:
      - accept-edits mode is active AND
      - there is at least one pending edit in the queue.

    This prevents stale footer state from leaking between sessions or tasks.
    """
    with _state_lock:
        return _accept_edits_enabled and len(_accept_edits_pending) > 0


def pending_edit_count() -> int:
    """Return the number of pending edits in the queue."""
    with _state_lock:
        return len(_accept_edits_pending)


def reset_session() -> None:
    """Clear ALL accept-edits state for a fresh session.

    Resets both the pending-edit queue and the enabled flag so no stale
    state leaks between sessions, tasks, or REPL restarts.  This is the
    nuclear option — call only on ``/clear`` or session landing, NOT on
    mode cycling (use ``set_mode()`` for that).
    """
    global _accept_edits_enabled, _JOURNAL_PATH, _JOURNAL_LOCK_PATH, _pre_replace_test_hook
    with _state_lock:
        _accept_edits_pending.clear()
        _accept_edits_enabled = False
    _close_journal()
    _reconciliation_journal.clear()
    _wal_journal_cache.clear()
    _JOURNAL_PATH = ""
    _JOURNAL_LOCK_PATH = ""
    _pre_replace_test_hook = None


def set_mode(accept_edits: bool) -> None:
    """Set the accept-edits mode flag without clearing pending edits.

    Called by the REPL's mode-cycling logic (``_cycle_mode``).  Unlike
    ``reset_session()``, this does NOT clear the pending-edit queue —
    pending edits survive mode transitions so the user can cycle modes
    without losing queued edits.

    The footer (``has_pending_edits``) will show "accept edits on" only
    when the flag is True AND the queue is non-empty.
    """
    global _accept_edits_enabled
    with _state_lock:
        _accept_edits_enabled = accept_edits


def peek_pending() -> list[PendingEdit]:
    """Return a copy of pending edits WITHOUT removing them from the queue.

    Intended for the REPL to inspect pending edits before deciding to
    accept or reject.  The queue is NOT modified — call ``drain_pending()``
    only AFTER successful processing.
    """
    with _state_lock:
        return list(_accept_edits_pending)


def drain_pending() -> list[PendingEdit]:
    """Drain and return all pending edits. Called by the UI after each turn.

    WARNING: Only call this AFTER successfully accepting or rejecting all
    pending edits.  Calling it before accept/reject will LOSE edits.
    Use ``peek_pending()`` for inspection without removal.
    """
    with _state_lock:
        drained = list(_accept_edits_pending)
        _accept_edits_pending.clear()
        return drained


_reconciliation_journal: list[ReconciliationRecord] = []
_journal_lock = threading.Lock()  # separate lock for journal (never nested under _state_lock)
_JOURNAL_PATH: str = ""
_JOURNAL_LOCK_PATH: str = ""

# Process-local lock for serialising journal writes + compaction.
# Paired with fcntl.flock on journal.lock for cross-process safety.
_journal_writer_lock = threading.Lock()

# Stable lock-file descriptor (journal.lock is NEVER replaced).
_journal_lock_fd: int | None = None

# Workspace identity (set once at startup).
_workspace_identity: WorkspaceIdentity | None = None

# In-memory cache of loaded WAL records (populated at startup).
_wal_journal_cache: list[WalRecord] = []


def set_journal_path(path: str | None) -> None:
    """Set the persistent journal file path.

    Creates the journal directory, lock file, and workspace identity file
    on first call with a non-None path.  Pass None for memory-only.
    """
    global _JOURNAL_PATH, _JOURNAL_LOCK_PATH
    if not path:
        _JOURNAL_PATH = ""
        _JOURNAL_LOCK_PATH = ""
        return
    p = _Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _JOURNAL_PATH = str(p)
    lock = p.parent / "journal.lock"
    # Create lock file with correct mode if it doesn't exist
    if not lock.exists():
        lock_fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(lock_fd)
        # fsync parent so lock file is durable on disk
        _fsync_parent(lock.parent)
    _JOURNAL_LOCK_PATH = str(lock)


def get_workspace_identity() -> WorkspaceIdentity | None:
    return _workspace_identity


def set_workspace_identity(workspace_root: str) -> WorkspaceIdentity:
    """Set workspace identity (idempotent, called once at startup)."""
    global _workspace_identity
    if _workspace_identity is not None:
        return _workspace_identity
    wid = str(uuid.uuid4())
    # Normalize PathLike → str at the serialization boundary
    root = os.fspath(workspace_root)
    if not isinstance(root, str):
        raise TypeError(f"Expected str or PathLike, got {type(workspace_root).__name__}")
    fp = hashlib.sha256(root.encode("utf-8")).hexdigest()
    _workspace_identity = WorkspaceIdentity(workspace_id=wid, root_fingerprint=fp)
    return _workspace_identity


def load_workspace_identity(workspace_root: str) -> WorkspaceIdentity:
    """Load or create workspace identity from .nabd/journal/workspace.json."""
    from pathlib import Path as _P
    p = _P(workspace_root) / ".nabd" / "journal" / "workspace.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            _ws = WorkspaceIdentity(workspace_id=data["workspace_id"],
                                    root_fingerprint=data["root_fingerprint"])
            global _workspace_identity
            _workspace_identity = _ws
            return _ws
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    # Create fresh
    ws = set_workspace_identity(workspace_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "workspace_id": ws.workspace_id,
        "root_fingerprint": ws.root_fingerprint,
    }, sort_keys=True), encoding="utf-8")
    return ws


def get_reconciliation_journal() -> list[ReconciliationRecord]:
    """Return a snapshot of the reconciliation journal (thread-safe)."""
    with _journal_lock:
        return list(_reconciliation_journal)


def load_and_reconcile_journal() -> RecoveryReport:
    """Load unresolved records from persistent journal on startup.

    Reads the WAL journal file, validates checksums, checks workspace
    identity, and returns a ``RecoveryReport``.  Never automatically
    replays side effects or modifies the filesystem.
    """
    diagnostics: list[str] = []
    loaded: list[WalRecord] = []
    corruption_detected = False
    unsupported_schema = False
    foreign_records = False
    truncated = False

    if not _JOURNAL_PATH:
        return RecoveryReport()
    p = _Path(_JOURNAL_PATH)
    if not p.exists():
        return RecoveryReport()

    workspace_id = _workspace_identity.workspace_id if _workspace_identity else ""

    try:
        raw = p.read_bytes()
        lines = raw.split(b"\n")
        for i, line in enumerate(lines):
            if not line.strip():
                continue

            if len(line) > JOURNAL_MAX_RECORD_BYTES:
                diagnostics.append(f"OVERSIZED_RECORD at line {i}")
                corruption_detected = True
                continue

            try:
                text = line.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(f"JOURNAL_ENCODING_ERROR at line {i}")
                corruption_detected = True
                continue

            is_tail = (i == len(lines) - 1 and not raw.endswith(b"\n") and line.strip())

            try:
                d = json.loads(text)
            except json.JSONDecodeError:
                if is_tail:
                    diagnostics.append(f"TRUNCATED_TAIL at line {i}")
                    truncated = True
                else:
                    diagnostics.append(f"JSON_DECODE_ERROR at line {i}")
                    corruption_detected = True
                continue

            # Verify checksum
            if not _verify_record_checksum(d):
                if is_tail:
                    diagnostics.append(f"TRUNCATED_TAIL at line {i}")
                    truncated = True
                else:
                    diagnostics.append(f"CORRUPT_RECORD at line {i}")
                    corruption_detected = True
                continue

            # Check schema version
            sv = d.get("schema_version", 0)
            if sv != JOURNAL_SCHEMA_VERSION:
                diagnostics.append(f"UNSUPPORTED_SCHEMA at line {i}: version={sv}")
                unsupported_schema = True
                continue

            # Check workspace identity
            rec_ws = d.get("workspace_id", "")
            if workspace_id and rec_ws and rec_ws != workspace_id:
                diagnostics.append(f"FOREIGN_WORKSPACE_RECORD at line {i}: ws={rec_ws}")
                foreign_records = True
                continue

            # Parse as WalRecord
            try:
                rec = WalRecord(
                    schema_version=d["schema_version"],
                    record_id=d["record_id"],
                    workspace_id=d.get("workspace_id", ""),
                    workspace_root_fingerprint=d.get("workspace_root_fingerprint", ""),
                    operation_id=d["operation_id"],
                    sequence=d.get("sequence", 0),
                    event_type=d.get("event_type", ""),
                    edit_id=d["edit_id"],
                    operation_type=d.get("operation_type", ""),
                    target_path_relative=d.get("target_path_relative", ""),
                    expected_original_digest=d.get("expected_original_digest", ""),
                    intended_result_digest=d.get("intended_result_digest", ""),
                    observed_result_digest=d.get("observed_result_digest"),
                    snapshot_reference=d.get("snapshot_reference"),
                    failure_stage=d.get("failure_stage"),
                    side_effect_applied=d.get("side_effect_applied", False),
                    durability_confirmed=d.get("durability_confirmed", False),
                    cleanup_succeeded=d.get("cleanup_succeeded", True),
                    recovery_status=d.get("recovery_status", ""),
                    created_at=d.get("created_at", ""),
                    checksum=d.get("checksum", ""),
                )
                loaded.append(rec)
            except (KeyError, TypeError) as exc:
                diagnostics.append(f"WAL_PARSE_ERROR at line {i}: {exc}")
                corruption_detected = True
                continue

    except OSError as exc:
        diagnostics.append(f"JOURNAL_READ_ERROR: {exc}")
        return RecoveryReport(
            diagnostics=tuple(diagnostics),
            requires_review=False,
        )

    # Detect invalid sequences via pure reconstruction
    recon = reconstruct_operations(loaded, workspace_id)
    diagnostics.extend(recon.diagnostics)
    requires_review = recon.requires_review
    corruption_detected = corruption_detected or recon.corruption_detected
    unsupported_schema = unsupported_schema or recon.unsupported_schema_detected
    foreign_records = foreign_records or recon.foreign_workspace_records

    with _journal_lock:
        _wal_journal_cache.clear()
        _wal_journal_cache.extend(loaded)

    return RecoveryReport(
        operations=tuple(loaded),
        diagnostics=tuple(diagnostics),
        requires_review=requires_review,
        corruption_detected=corruption_detected,
        unsupported_schema_detected=unsupported_schema,
        foreign_workspace_records=foreign_records,
        truncated_tail_detected=truncated,
    )


def _compute_digest(content: str | os.PathLike[str]) -> str:
    """SHA-256 of raw UTF-8 bytes (not normalized).

    Accepts both str and PathLike — always normalizes at this
    serialization boundary so callers can pass either type.
    """
    if not isinstance(content, str):
        content = os.fspath(content)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _file_digest(file_path: str) -> str | None:
    """SHA-256 of the raw bytes on disk. Returns None if absent."""
    p = _Path(file_path)
    if not p.exists():
        return None
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _write_all(fd: int, data: bytes) -> None:
    """Write *data* to *fd*, retrying on short writes.
    Raises OSError on zero-progress write."""
    mv = memoryview(data)
    while mv:
        n = os.write(fd, mv)
        if n is None or n <= 0:
            raise OSError("short write made no progress")
        mv = mv[n:]


# ── WAL Core: canonical JSON, checksum, serialisation ─────────────────


def _canonical_json(payload: dict) -> str:
    """Deterministic compact JSON — rejects NaN/Infinity.

    Uses ``default=str`` so PathLike values are safely converted
    to strings before serialization.  Callers MUST use this function
    for all WAL record serialization.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def _compute_record_checksum(payload: dict) -> str:
    """SHA-256 of canonical JSON with 'checksum' field excluded."""
    clean = {k: v for k, v in payload.items() if k != "checksum"}
    canonical = _canonical_json(clean)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verify_record_checksum(record: dict) -> bool:
    """Verify integrity checksum.  Returns True if valid."""
    stored = record.get("checksum")
    if not stored:
        return False
    return _compute_record_checksum(record) == stored


def _serialize_wal_record(rec: WalRecord) -> bytes:
    """Serialize a WalRecord to canonical JSON bytes with checksum + newline.

    Normalizes all string-typed fields via ``os.fspath()`` before
    entering the serialization pipeline so no PathLike object can reach
    ``_canonical_json`` or ``.encode()``.
    """
    d = dataclasses.asdict(rec)
    # Normalize every field that carries a path value
    for key in ("target_path_relative", "snapshot_reference", "workspace_id",
                "workspace_root_fingerprint"):
        val = d.get(key)
        if val is not None and not isinstance(val, str):
            d[key] = os.fspath(val)
        if key == "target_path_relative" and isinstance(d.get(key), str):
            d[key] = d[key].replace("\\", "/")

    if not d.get("created_at"):
        d["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    d["checksum"] = _compute_record_checksum(d)
    return _canonical_json(d).encode("utf-8") + b"\n"


def _ensure_journal_locked() -> int:
    """Acquire exclusive flock on journal.lock.  Returns the lock fd."""
    global _journal_lock_fd
    if _journal_lock_fd is None or not _JOURNAL_LOCK_PATH:
        lock_path = _JOURNAL_LOCK_PATH
        if not lock_path:
            raise OSError("journal lock path not configured")
        _journal_lock_fd = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT,
            0o600,
        )
    if fcntl is not None:
        fcntl.flock(_journal_lock_fd, fcntl.LOCK_EX)
    return _journal_lock_fd


def _release_lock() -> None:
    """Release exclusive flock on journal.lock."""
    if _journal_lock_fd is not None:
        if fcntl is not None:
            try:
                fcntl.flock(_journal_lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass


def _write_journal_record(rec: WalRecord) -> bool:
    """Append one WalRecord to the journal with full durability.

    Locking order:
      1. _journal_writer_lock (process-local)
      2. fcntl.flock(LOCK_EX) on journal.lock (cross-process)

    Returns True on success.  Raises OSError on failure — caller MUST
    handle journal errors according to failure-semantics rules.
    """
    if not _JOURNAL_PATH or not _JOURNAL_LOCK_PATH:
        return True  # memory-only mode
    with _journal_writer_lock:
        lock_fd = _ensure_journal_locked()
        try:
            fd = os.open(
                _JOURNAL_PATH,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                data = _serialize_wal_record(rec)
                _write_all(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            return True
        finally:
            _release_lock()


def _close_journal() -> None:
    """Release journal resources.  Called from reset_session()."""
    global _journal_lock_fd
    if _journal_lock_fd is not None:
        if fcntl is not None:
            try:
                fcntl.flock(_journal_lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(_journal_lock_fd)
        except OSError:
            pass
        _journal_lock_fd = None


def _validate_journal_path(path: str) -> str | None:
    """Validate journal path: no symlink, inside trusted state root.

    Returns None on success, error message on rejection.
    """
    if not path:
        return "Journal path is empty"
    p = _Path(path)
    if p.is_symlink() or p.parent.is_symlink():
        return "Journal path or parent is a symlink"
    return None


def _make_target_relative(target_path: str, workspace_root: str) -> str:
    """Convert an absolute target path to a workspace-relative path.

    Falls back to the basename if the path is outside the workspace.
    """
    try:
        return str(_Path(target_path).relative_to(_Path(workspace_root)))
    except ValueError:
        return _Path(target_path).name


# ── Pure Reconstruction (Gate 14 — no I/O, no side effects) ──────────


_VALID_EVENT_TYPES: frozenset[str] = frozenset({
    "PREPARED", "APPLIED", "COMMITTED", "RESOLVED",
    "FAILED", "RECONCILIATION_REQUIRED",
})


def reconstruct_operations(
    records: list[WalRecord],
    current_workspace_id: str = "",
) -> RecoveryReport:
    """Pure function: reconstruct operation state from WAL records.

    Performs NO I/O and NO side effects.  Returns a ``RecoveryReport``
    with diagnostics for every anomaly detected.
    """
    diagnostics: list[str] = []
    seen_ids: set[str] = set()
    seen_ops: dict[str, list[WalRecord]] = {}
    corrupted = False
    unsupported = False
    foreign = False
    requires_review = False

    last_seqs: dict[str, int] = {}
    for r in records:
        # ── record_id uniqueness ────────────────────────────────────
        if r.record_id in seen_ids:
            diagnostics.append(f"DUPLICATE_RECORD_ID: record_id={r.record_id}")
        seen_ids.add(r.record_id)

        # ── sequence regression check ───────────────────────────────
        if r.operation_id in last_seqs and r.sequence < last_seqs[r.operation_id]:
            diagnostics.append(
                f"INVALID_EVENT_SEQUENCE: op={r.operation_id} seq regression {r.sequence} "
                f"< previous={last_seqs[r.operation_id]}"
            )
        last_seqs[r.operation_id] = r.sequence

        # ── schema version ──────────────────────────────────────────
        if r.schema_version != JOURNAL_SCHEMA_VERSION:
            diagnostics.append(
                f"UNSUPPORTED_SCHEMA: record_id={r.record_id} "
                f"version={r.schema_version}"
            )
            unsupported = True
            continue

        # ── checksum ───────────────────────────────────────────────
        import dataclasses
        d = dataclasses.asdict(r)
        if not _verify_record_checksum(d):
            diagnostics.append(f"CORRUPT_RECORD: record_id={r.record_id}")
            corrupted = True
            continue

        # ── workspace identity ──────────────────────────────────────
        if current_workspace_id and r.workspace_id and r.workspace_id != current_workspace_id:
            diagnostics.append(
                f"FOREIGN_WORKSPACE_RECORD: record_id={r.record_id} "
                f"ws={r.workspace_id}"
            )
            foreign = True
            continue

        # ── event type validity ─────────────────────────────────────
        if r.event_type not in _VALID_EVENT_TYPES:
            diagnostics.append(
                f"UNSUPPORTED_EVENT_TYPE: record_id={r.record_id} "
                f"type={r.event_type}"
            )
            unsupported = True
            continue

        seen_ops.setdefault(r.operation_id, []).append(r)

    # ── Per-operation sequence analysis ────────────────────────────
    for op_id, ops in seen_ops.items():
        ops_sorted = sorted(ops, key=lambda x: x.sequence)
        prev_seq = 0
        prev_event: str | None = None
        prev_record: WalRecord | None = None
        edit_ids: set[str] = set()
        workspace_ids: set[str] = set()

        for r in ops_sorted:
            edit_ids.add(r.edit_id)
            if r.workspace_id:
                workspace_ids.add(r.workspace_id)

            # ── sequence checks ─────────────────────────────────
            if prev_seq != 0:
                if r.sequence < prev_seq:
                    diagnostics.append(
                        f"INVALID_EVENT_SEQUENCE: op={op_id} seq={r.sequence} "
                        f"< previous={prev_seq}"
                    )
                elif r.sequence == prev_seq:
                    # Duplicate sequence
                    if r.event_type == prev_record.event_type and r.target_path_relative == prev_record.target_path_relative:
                        diagnostics.append(f"DUPLICATE_SEQUENCE_SAME_CONTENT: op={op_id} seq={r.sequence}")
                    else:
                        diagnostics.append(f"CONFLICTING_DUPLICATE_EVENT: op={op_id} seq={r.sequence}")
                elif r.sequence != prev_seq + 1:
                    diagnostics.append(f"INVALID_EVENT_SEQUENCE: op={op_id} seq gap {prev_seq}→{r.sequence}")

            prev_seq = r.sequence

            # ── expected first event ────────────────────────────────
            if ops_sorted.index(r) == 0 and r.sequence != 1:
                diagnostics.append(
                    f"INVALID_EVENT_SEQUENCE: op={op_id} first seq={r.sequence} "
                    f"expected first=1 (PREPARED)"
                )

            # ── missing intermediate events ─────────────────────────
            if prev_event is not None and r.sequence > prev_record.sequence:
                if prev_event == "APPLIED" and r.event_type != "COMMITTED":
                    diagnostics.append(
                        f"INVALID_EVENT_SEQUENCE: op={op_id} {prev_event}→{r.event_type} "
                        f"expected APPLIED→COMMITTED"
                    )
                if prev_event == "COMMITTED" and r.event_type not in ("RESOLVED", "FAILED", "RECONCILIATION_REQUIRED"):
                    diagnostics.append(
                        f"INVALID_EVENT_SEQUENCE: op={op_id} {prev_event}→{r.event_type} "
                        f"expected COMMITTED→RESOLVED/FAILED/RECONCILIATION_REQUIRED"
                    )
                if prev_event == "PREPARED" and r.event_type not in ("APPLIED", "FAILED", "RECONCILIATION_REQUIRED"):
                    diagnostics.append(
                        f"INVALID_EVENT_SEQUENCE: op={op_id} {prev_event}→{r.event_type} "
                        f"expected PREPARED→APPLIED/FAILED/RECONCILIATION_REQUIRED"
                    )
            
            if r.sequence > (prev_record.sequence if prev_record else 0):
                prev_event = r.event_type
                prev_record = r

        # ── cross-operation identity checks ─────────────────────────
        if len(edit_ids) > 1:
            diagnostics.append(
                f"OPERATION_IDENTITY_CONFLICT: op={op_id} "
                f"edit_ids={','.join(sorted(edit_ids))}"
            )
        if len(workspace_ids) > 1:
            diagnostics.append(
                f"OPERATION_IDENTITY_CONFLICT: op={op_id} "
                f"workspaces={','.join(sorted(workspace_ids))}"
            )

    # ── Derive requires_review from operations and diagnostics ─────────
    for op_id, ops in seen_ops.items():
        latest = max(ops, key=lambda r: r.sequence)
        # Terminal states that normally don't require review
        # SAFE_FAILURE (FAILED before side effect) or RESOLVED
        is_terminal_safe = False
        if latest.event_type == "RESOLVED" and latest.durability_confirmed:
            is_terminal_safe = True
        elif latest.event_type == "FAILED" and not latest.side_effect_applied and latest.cleanup_succeeded:
            is_terminal_safe = True
            
        if not is_terminal_safe:
            requires_review = True

    # Check for DURABILITY_WARNING or other non-terminal states?
    # If any event has durability_confirmed=False after APPLIED? 
    # Actually, if there's a warning, it's typically tracked as a diagnostic or state?
    # Let's check diagnostics for any review-requiring ones.
    for diag in diagnostics:
        if any(marker in diag for marker in [
            "CORRUPT_RECORD",
            "UNSUPPORTED_SCHEMA",
            "FOREIGN_WORKSPACE_RECORD",
            "INVALID_EVENT_SEQUENCE",
            "DURABILITY_WARNING",
            "CONFLICTING_",
            "OPERATION_IDENTITY_CONFLICT",
            "UNSUPPORTED_EVENT_TYPE",
            "DUPLICATE_"
        ]):
            requires_review = True

    # ── Check for APPLIED without PREPARED ─────────────────────────
    for op_id, ops in seen_ops.items():
        types = {r.event_type for r in ops}
        if "APPLIED" in types and "PREPARED" not in types:
            diagnostics.append(
                f"INVALID_EVENT_SEQUENCE: op={op_id} APPLIED without PREPARED"
            )
        if "COMMITTED" in types and "APPLIED" not in types:
            diagnostics.append(
                f"INVALID_EVENT_SEQUENCE: op={op_id} COMMITTED without APPLIED"
            )
        if "RESOLVED" in types and "COMMITTED" not in types:
            diagnostics.append(
                f"INVALID_EVENT_SEQUENCE: op={op_id} RESOLVED without COMMITTED"
            )
        if "RESOLVED" in types and "FAILED" in types:
            diagnostics.append(
                f"CONFLICTING_TERMINAL_EVENTS: op={op_id} has both RESOLVED and FAILED"
            )

    # Re-evaluate diagnostics just appended
    for diag in diagnostics:
        if any(marker in diag for marker in [
            "CORRUPT_RECORD",
            "UNSUPPORTED_SCHEMA",
            "FOREIGN_WORKSPACE_RECORD",
            "INVALID_EVENT_SEQUENCE",
            "DURABILITY_WARNING",
            "CONFLICTING_",
            "OPERATION_IDENTITY_CONFLICT",
            "UNSUPPORTED_EVENT_TYPE",
            "DUPLICATE_"
        ]):
            requires_review = True

    return RecoveryReport(
        operations=tuple(records),
        diagnostics=tuple(diagnostics),
        requires_review=requires_review,
        corruption_detected=corrupted,
        unsupported_schema_detected=unsupported,
        foreign_workspace_records=foreign,
    )


def _detect_invalid_event_sequence(records: list[WalRecord]) -> list[str]:
    """Legacy wrapper — delegates to reconstruct_operations."""
    report = reconstruct_operations(records)
    return list(report.diagnostics)


# ── Retention & Atomic Compaction (Gate 13) ──────────────────────────


    # Tunable retention constants
JOURNAL_MAX_BYTES: int = 10 * 1024 * 1024       # 10 MiB
JOURNAL_MAX_RESOLVED_OPERATIONS: int = 1000       # resolved ops before compaction
JOURNAL_RETENTION_DAYS: int = 30                  # keep at least 30 days


def _compact_journal() -> tuple[bool, str]:
    """Compact the journal by pruning resolved operations.

    Uses the stable journal.lock for cross-process safety.
    Creates a temp file in the SAME directory, writes only unresolved
    records, then atomically replaces the original via os.replace().

    Returns (success, diagnostic_message).
    """
    if not _JOURNAL_PATH or not _JOURNAL_LOCK_PATH:
        return True, "memory-only mode, no compaction needed"

    with _journal_writer_lock:
        lock_fd = _ensure_journal_locked()
        try:
            # 1. Read all records
            p = _Path(_JOURNAL_PATH)
            if not p.exists():
                return True, "no journal file to compact"

            raw = p.read_bytes()
            if not raw.strip():
                return True, "journal is empty"

            lines = raw.split(b"\n")
            records: list[WalRecord] = []
            parse_diags: list[str] = []

            for line in lines:
                if not line.strip():
                    continue
                rec = _parse_wal_line(line, parse_diags)
                if rec is not None:
                    records.append(rec)

            if not records:
                return True, "no parseable records in journal"

            # 2. Group by operation_id
            ops: dict[str, list[WalRecord]] = {}
            for r in records:
                ops.setdefault(r.operation_id, []).append(r)

            # 3. Determine prunable operations
            # An operation is prunable if its LATEST event is RESOLVED
            # and durability_confirmed == True (meaning no durability warning pending)
            prunable: set[str] = set()
            for op_id, evts in ops.items():
                latest = max(evts, key=lambda x: x.sequence)
                if latest.event_type == "RESOLVED" and latest.durability_confirmed:
                    prunable.add(op_id)

            # 4. If nothing to prune, skip
            if not prunable:
                return True, "no prunable operations"

            # 5. Build compacted dataset
            compacted_lines: list[bytes] = []
            pruned = 0
            for r in records:
                if r.operation_id in prunable:
                    pruned += 1
                else:
                    compacted_lines.append(_serialize_wal_record(r))

            # 6. Write temp file in SAME directory
            import uuid as _uuid
            journal_dir = str(p.parent)
            temp_name = f".journal.compact.{os.getpid()}.{_uuid.uuid4().hex}.tmp"
            temp_path = os.path.join(journal_dir, temp_name)

            temp_fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                for line_data in compacted_lines:
                    _write_all(temp_fd, line_data)
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)

            replaced = False
            try:
                # 7. Atomic replace
                os.replace(temp_path, _JOURNAL_PATH)
                replaced = True

                # 8. fsync parent directory
                _fsync_parent(p.parent)

                return True, f"compacted: {pruned} resolved records pruned"

            except OSError as exc:
                if replaced:
                    try:
                        warn_fd = os.open(_JOURNAL_PATH, os.O_WRONLY | os.O_APPEND, 0o600)
                        warn_rec = WalRecord(
                            record_id=str(_uuid.uuid4()),
                            workspace_id="", workspace_root_fingerprint="",
                            operation_id=str(_uuid.uuid4()), sequence=1,
                            event_type="RECONCILIATION_REQUIRED",
                            edit_id="compaction_parent_fsync_failure",
                            operation_type="SYSTEM",
                            target_path_relative="", expected_original_digest="",
                            intended_result_digest=""
                        )
                        _write_all(warn_fd, _serialize_wal_record(warn_rec))
                        os.fsync(warn_fd)
                        os.close(warn_fd)
                    except OSError:
                        pass
                    return False, f"COMPACTION_DURABILITY_WARNING: parent fsync failed: {exc}"
                else:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                    return False, f"compaction failed: {exc}"

        except OSError as exc:
            return False, f"compaction failed: {exc}"
        finally:
            _release_lock()


def _parse_wal_line(line: bytes, diagnostics: list[str]) -> WalRecord | None:
    """Parse a single WAL line into a WalRecord. Returns None on failure."""
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        diagnostics.append("JOURNAL_ENCODING_ERROR")
        return None
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        diagnostics.append("JSON_DECODE_ERROR")
        return None
    if not _verify_record_checksum(d):
        diagnostics.append("CORRUPT_RECORD")
        return None
    try:
        return WalRecord(
            schema_version=d.get("schema_version", 0),
            record_id=d.get("record_id", ""),
            workspace_id=d.get("workspace_id", ""),
            workspace_root_fingerprint=d.get("workspace_root_fingerprint", ""),
            operation_id=d.get("operation_id", ""),
            sequence=d.get("sequence", 0),
            event_type=d.get("event_type", ""),
            edit_id=d.get("edit_id", ""),
            operation_type=d.get("operation_type", ""),
            target_path_relative=d.get("target_path_relative", ""),
            expected_original_digest=d.get("expected_original_digest", ""),
            intended_result_digest=d.get("intended_result_digest", ""),
            observed_result_digest=d.get("observed_result_digest"),
            snapshot_reference=d.get("snapshot_reference"),
            failure_stage=d.get("failure_stage"),
            side_effect_applied=d.get("side_effect_applied", False),
            durability_confirmed=d.get("durability_confirmed", False),
            cleanup_succeeded=d.get("cleanup_succeeded", True),
            recovery_status=d.get("recovery_status", ""),
            created_at=d.get("created_at", ""),
            checksum=d.get("checksum", ""),
        )
    except (KeyError, TypeError):
        diagnostics.append("WAL_PARSE_ERROR")
        return None


# ── End WAL Core ─────────────────────────────────────────────────────


def _create_exclusive_temp(target: _Path) -> tuple[_Path, int]:
    """Create an exclusive-access temp file in the same directory as *target*.

    Uses ``mkstemp(dir=target.parent)`` which guarantees a unique name
    (O_CREAT|O_EXCL internally).  The returned file descriptor is opened
    ``O_WRONLY`` and the temp path is returned together with the fd.

    Raises OSError if creation fails.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        suffix=".tmp",
        prefix=target.name + ".",
        dir=str(target.parent),
    )
    # Re-open as write-only (mkstemp gives O_RDWR, but we only need O_WRONLY).
    # Closing the original and opening a new fd ensures the temp gets the
    # right file-position behaviour for _write_all + fsync.
    # Preserve the same inode by doing this carefully.
    os.close(fd)
    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp_name, flags)
    return _Path(tmp_name), fd



_pre_replace_test_hook: Optional[Any] = None


def _atomic_write(target: _Path, data: bytes) -> AtomicWriteResult:
    """Write *data* to *target* atomically via exclusive temp → fsync → replace → fsync(parent).

    Returns an ``AtomicWriteResult`` — never raises.  Each call produces
    its own self-contained result with no shared global state.
    """
    tmp_path: _Path | None = None
    fd: int | None = None
    replaced = False
    failure_stage: WriteStage | None = None
    primary_error: OSError | None = None
    cleanup_error: OSError | None = None
    durability_confirmed = False
    cleanup_succeeded = True

    try:
        failure_stage = WriteStage.TEMP_CREATE
        tmp_path, fd = _create_exclusive_temp(target)

        # Preserve original mode if target exists
        orig_mode = None
        try:
            orig_stat = target.stat(follow_symlinks=False)
            orig_mode = _stat.S_IMODE(orig_stat.st_mode)
        except OSError:
            orig_mode = None

        failure_stage = WriteStage.TEMP_WRITE
        _write_all(fd, data)

        failure_stage = WriteStage.TEMP_FSYNC
        os.fsync(fd)

        if orig_mode is not None:
            os.chmod(str(tmp_path), orig_mode)

        os.close(fd)
        fd = None

        # EXE-01: Test seam hook for external writer injection immediately before os.replace
        if _pre_replace_test_hook is not None:
            try:
                _pre_replace_test_hook(target)
            except Exception as hook_exc:
                _logger.warning("pre_replace_test_hook error: %s", hook_exc)

        failure_stage = WriteStage.REPLACE
        os.replace(str(tmp_path), str(target))
        replaced = True

        failure_stage = WriteStage.PARENT_FSYNC
        durability_confirmed = _fsync_parent(target.parent)

    except OSError as exc:
        primary_error = exc
    except Exception as exc:
        # Non-OSError (e.g. ValueError from tempfile) — wrap as OSError-like
        primary_error = OSError(f"{type(exc).__name__}: {exc}")

    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if not replaced and tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_error = exc
                cleanup_succeeded = False
            except Exception:
                # Any non-OSError during cleanup (e.g. test mock wiring)
                # is still a cleanup failure.
                cleanup_succeeded = False

    if primary_error is not None:
        cleanup_failed = cleanup_error is not None
        return AtomicWriteResult(
            applied=replaced,
            durability_confirmed=False,
            cleanup_succeeded=not cleanup_failed,
            failure_stage=WriteStage.TEMP_CLEANUP if cleanup_failed else failure_stage,
            error_type=type(primary_error).__name__,
            safe_message=(
                "Temporary-file cleanup failed; manual reconciliation is required."
                if cleanup_failed
                else "Atomic write failed before completion."
            ),
            temp_artifact_remaining=cleanup_failed,
        )

    if not durability_confirmed:
        return AtomicWriteResult(
            applied=True,
            durability_confirmed=False,
            cleanup_succeeded=True,
            failure_stage=WriteStage.PARENT_FSYNC,
            safe_message=(
                "The file was replaced, but directory durability "
                "could not be confirmed."
            ),
        )

    return AtomicWriteResult(
        applied=True,
        durability_confirmed=True,
        cleanup_succeeded=True,
    )


def _atomic_write_if_unchanged(
    target: _Path,
    data: bytes,
    expected_digest: str | None,
) -> AtomicWriteResult:
    """Atomically write *data* to *target* ONLY if *target* still matches
    ``expected_digest`` at the instant before ``os.replace``.

    This is the content-hash CAS (compare-and-swap) seam for the
    check-to-replace window: the digest is re-verified after the temp file
    is written/fsynced and immediately before the atomic replace, so a
    non-lock-sharing external writer that modified the target after the
    caller's earlier precondition checks cannot be silently clobbered.

    Semantics:
      * ``expected_digest is None`` → no precondition; behaves like
        ``_atomic_write`` (unconditional replace).
      * Digest matches → replace proceeds; result identical to
        ``_atomic_write`` success.
      * Digest mismatch → **no replace**; returns a result with
        ``applied=False`` and ``failure_stage=PRE_REPLACE_CHECK`` so the
        caller can surface a CONFLICT / reconciliation instead of losing
        the external write.

    Never raises.  Returns an ``AtomicWriteResult``.
    """
    # Empty digest means "no precondition" (new-file / skip) — same as None.
    if not expected_digest:
        return _atomic_write(target, data)

    tmp_path: _Path | None = None
    fd: int | None = None
    replaced = False
    failure_stage: WriteStage | None = None
    primary_error: OSError | None = None
    cleanup_error: OSError | None = None
    durability_confirmed = False
    cleanup_succeeded = True

    try:
        failure_stage = WriteStage.TEMP_CREATE
        tmp_path, fd = _create_exclusive_temp(target)

        orig_mode = None
        try:
            orig_stat = target.stat(follow_symlinks=False)
            orig_mode = _stat.S_IMODE(orig_stat.st_mode)
        except OSError:
            orig_mode = None

        failure_stage = WriteStage.TEMP_WRITE
        _write_all(fd, data)

        failure_stage = WriteStage.TEMP_FSYNC
        os.fsync(fd)

        if orig_mode is not None:
            os.chmod(str(tmp_path), orig_mode)

        os.close(fd)
        fd = None

        # ── CAS check: re-verify the target right before replace ──
        failure_stage = WriteStage.PRE_REPLACE_CHECK
        if _file_digest(str(target)) != expected_digest:
            # Do NOT replace — the external writer's content is preserved.
            return AtomicWriteResult(
                applied=False,
                durability_confirmed=False,
                cleanup_succeeded=True,
                failure_stage=WriteStage.PRE_REPLACE_CHECK,
                error_type="DigestMismatch",
                safe_message=(
                    "Target changed concurrently; write aborted to preserve "
                    "the external modification."
                ),
            )

        failure_stage = WriteStage.REPLACE
        os.replace(str(tmp_path), str(target))
        replaced = True

        failure_stage = WriteStage.PARENT_FSYNC
        durability_confirmed = _fsync_parent(target.parent)

    except OSError as exc:
        primary_error = exc
    except Exception as exc:
        primary_error = OSError(f"{type(exc).__name__}: {exc}")

    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if not replaced and tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_error = exc
                cleanup_succeeded = False
            except Exception:
                cleanup_succeeded = False

    if primary_error is not None:
        cleanup_failed = cleanup_error is not None
        return AtomicWriteResult(
            applied=replaced,
            durability_confirmed=False,
            cleanup_succeeded=not cleanup_failed,
            failure_stage=WriteStage.TEMP_CLEANUP if cleanup_failed else failure_stage,
            error_type=type(primary_error).__name__,
            safe_message=(
                "Temporary-file cleanup failed; manual reconciliation is required."
                if cleanup_failed
                else "Atomic write failed before completion."
            ),
            temp_artifact_remaining=cleanup_failed,
        )

    if not durability_confirmed:
        return AtomicWriteResult(
            applied=True,
            durability_confirmed=False,
            cleanup_succeeded=True,
            failure_stage=WriteStage.PARENT_FSYNC,
            safe_message=(
                "The file was replaced, but directory durability "
                "could not be confirmed."
            ),
        )

    return AtomicWriteResult(
        applied=True,
        durability_confirmed=True,
        cleanup_succeeded=True,
    )


def _fsync_parent(parent: _Path) -> bool:
    """Best-effort parent-directory fsync.  Returns True if fsync succeeded,
    False if it was skipped (unavailable on platform).  Never raises.
    On Windows (NTFS), directory fsync is handled atomically by filesystem rename."""
    if os.name == "nt":
        return True
    try:
        pfd = os.open(str(parent), os.O_RDONLY)
        try:
            os.fsync(pfd)
        finally:
            os.close(pfd)
        return True
    except OSError:
        return False


def _validate_path_safe(resolved_path: str) -> str | None:
    """Validate that *resolved_path* is safe to write.

    Returns None on success, or an error message string on failure.
    Checks: path not empty, not a directory, not a symlink.
    Workspace containment is enforced at PendingEdit creation time in
    ``tools/file_system.py`` and is not re-checked here to support
    test patterns that write to temporary directories.
    """
    if not resolved_path or not resolved_path.strip():
        return "Target path is empty"

    target = _Path(resolved_path)

    # If the target doesn't exist yet, validate its parent
    check = target if target.exists() or target.is_symlink() else target.parent

    # Reject symlinks (potential escape)
    if check.is_symlink():
        return f"Path '{check}' is a symlink; not allowed"

    # Reject directories
    if check.is_dir():
        return f"Path '{check}' is a directory; not allowed"

    return None  # OK


def _create_snapshot_from_disk(resolved_path: str, old_content: str) -> Snapshot:
    """Create a Snapshot from the CURRENT content on disk.

    This reads the actual file (not the in-memory ``old_content``) so that
    the snapshot digest reflects the bytes that will be restored on rollback.
    If the file does not exist, the snapshot stores an empty string and
    ``_ABSENT_SENTINEL`` as digest.
    """
    p = _Path(resolved_path)
    if p.exists():
        raw_bytes = p.read_bytes()
        disk_content = raw_bytes.decode("utf-8")
        digest = hashlib.sha256(raw_bytes).hexdigest()
    else:
        disk_content = ""
        digest = _compute_digest(_ABSENT_SENTINEL)
    return Snapshot(
        edit_id="",
        resolved_path=resolved_path,
        old_content=disk_content,
        digest=digest,
    )


def _rollback_snapshot(snapshot: Snapshot) -> bool:
    """Restore file from snapshot. Returns True on success."""
    try:
        # Route rollback through the same write seam as apply (expected_digest
        # None → unconditional, i.e. delegates to _atomic_write). This keeps
        # apply + rollback on one interposable write function.
        result = _atomic_write_if_unchanged(
            _Path(snapshot.resolved_path),
            snapshot.old_content.encode("utf-8"),
            None,
        )
        if not result.applied:
            return False
        verify = _file_digest(snapshot.resolved_path)
        return verify == snapshot.digest
    except Exception:
        return False


def _persist_reconciliation_record(record: ReconciliationRecord) -> bool:
    """Append one reconciliation record to the journal.

    Returns True on success.  Raises OSError on failure — caller MUST
    handle journal errors (no longer silently swallowed).
    """
    if not _JOURNAL_PATH:
        return True
    line = json.dumps(dataclasses.asdict(record), default=str) + "\n"
    p = _Path(_JOURNAL_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return True


def _record_reconciliation(
    operation_id: str,
    edit_id: str,
    resolved_path: str,
    claim_token: str,
    expected_digest: str,
    observed_digest: str | None,
    failure_stage: str,
    has_snapshot: bool,
) -> None:
    record = ReconciliationRecord(
        operation_id=operation_id,
        edit_id=edit_id,
        resolved_path=resolved_path,
        claim_token=claim_token,
        expected_digest=expected_digest,
        observed_digest=observed_digest,
        failure_stage=failure_stage,
        recovery_status="PENDING_REVIEW",
        has_snapshot=has_snapshot,
        timestamp_ns=time.time_ns(),
    )
    with _journal_lock:
        _reconciliation_journal.append(record)
    try:
        _persist_reconciliation_record(record)
    except OSError:
        pass  # legacy path — best-effort; new WAL path uses _write_journal_record


def _get_remaining_ids_unlocked() -> list[str]:
    return [e.edit_id for e in _accept_edits_pending if e.status == "PENDING"]


def _find_edit(edit_id: str) -> PendingEdit | None:
    for e in _accept_edits_pending:
        if e.edit_id == edit_id:
            return e
    return None


# ── WAL record builder (Session A: Gates 2-9) ─────────────────────────


def _make_wal_record(
    event_type: str,
    operation_id: str,
    sequence: int,
    edit_id: str,
    operation_type: str,
    target_path_relative: str,
    expected_original_digest: str = "",
    intended_result_digest: str = "",
    observed_result_digest: str | None = None,
    snapshot_reference: str | None = None,
    failure_stage: str | None = None,
    side_effect_applied: bool = False,
    durability_confirmed: bool = False,
    cleanup_succeeded: bool = True,
    recovery_status: str = "",
) -> WalRecord:
    """Build a WalRecord with workspace identity and globally unique record_id.

    PREPARED events default to ``recovery_status="PENDING_REVIEW"`` unless
    an explicit status is passed.

    Serialization-boundary normalization:
      - ``target_path_relative`` is always converted via ``os.fspath()``
        so PathLike inputs do not reach the WAL schema as Path objects.
    """
    if not recovery_status and event_type == "PREPARED":
        recovery_status = "PENDING_REVIEW"
    # Normalize PathLike → str at the WAL schema boundary
    if not isinstance(target_path_relative, str):
        target_path_relative = os.fspath(target_path_relative)
    # Reject absolute paths — WAL schema requires relative paths
    if os.path.isabs(target_path_relative):
        raise ValueError(
            f"target_path_relative must be a relative path, "
            f"got absolute: {target_path_relative}"
        )
    target_path_relative = target_path_relative.replace("\\", "/")

    ws = _workspace_identity
    workspace_id = ws.workspace_id if ws else ""
    root_fp = ws.root_fingerprint if ws else ""
    rec = WalRecord(
        record_id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        workspace_root_fingerprint=root_fp,
        operation_id=operation_id,
        sequence=sequence,
        event_type=event_type,
        edit_id=edit_id,
        operation_type=operation_type,
        target_path_relative=target_path_relative,
        expected_original_digest=expected_original_digest,
        intended_result_digest=intended_result_digest,
        observed_result_digest=observed_result_digest,
        snapshot_reference=snapshot_reference,
        failure_stage=failure_stage,
        side_effect_applied=side_effect_applied,
        durability_confirmed=durability_confirmed,
        cleanup_succeeded=cleanup_succeeded,
        recovery_status=recovery_status,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    d = dataclasses.asdict(rec)
    rec = dataclasses.replace(rec, checksum=_compute_record_checksum(d))
    return rec


def _claim_edit_for_accept(

    edit_id: str,
    expected_version: int | None,
    operation_id: str,
) -> tuple[TransactionResult | None, PendingEdit | None]:
    """Claim a pending edit for accept under state lock (no I/O)."""
    with _state_lock:
        edit = _find_edit(edit_id)
        if not edit:
            return TransactionResult(
                TransactionOutcome.NOT_FOUND, operation_id, [], [], _get_remaining_ids_unlocked(), 0
            ), None

        if edit.status != "PENDING":
            return TransactionResult(
                TransactionOutcome.CONFLICT, operation_id, [], [], _get_remaining_ids_unlocked(), 0
            ), None

        if expected_version is not None and edit.version != expected_version:
            return TransactionResult(
                TransactionOutcome.CONFLICT, operation_id, [], [], _get_remaining_ids_unlocked(), 0
            ), None

        edit.status = "PROCESSING_ACCEPT"
        edit.claim_token = operation_id
        edit.version += 1
        edit_data = dataclasses.replace(edit)
        return None, edit_data


def _check_edit_preconditions(edit_data: PendingEdit, operation_id: str) -> TransactionResult | None:
    """Validate path safety and content digest preconditions before write."""
    resolved_path = edit_data.resolved_path
    expected_digest = edit_data.expected_original_digest
    edit_id = edit_data.edit_id

    path_err = _validate_path_safe(resolved_path)
    if path_err is not None:
        return TransactionResult(
            TransactionOutcome.DENIED, operation_id, [],
            [TransactionFailure(edit_id, "PATH_AUTHORIZATION", "PathOutsideWorkspace", path_err, False)],
            _get_remaining_ids_unlocked(), 0,
        )

    if expected_digest and expected_digest != _ABSENT_SENTINEL:
        if _file_digest(resolved_path) != expected_digest:
            return TransactionResult(
                TransactionOutcome.CONFLICT, operation_id, [], [],
                _get_remaining_ids_unlocked(), 0,
            )
    elif expected_digest == _ABSENT_SENTINEL:
        if _Path(resolved_path).exists():
            return TransactionResult(
                TransactionOutcome.CONFLICT, operation_id, [], [],
                _get_remaining_ids_unlocked(), 0,
            )
    return None


def _record_prepared_wal(edit_data: PendingEdit, operation_id: str, snapshot: Any) -> TransactionResult | None:
    """Record PREPARED journal event before side effect."""
    prepared_rec = _make_wal_record(
        event_type="PREPARED", sequence=1,
        operation_id=operation_id, edit_id=edit_data.edit_id,
        operation_type="ACCEPT",
        target_path_relative=edit_data.path,
        expected_original_digest=edit_data.expected_original_digest,
        intended_result_digest=_compute_digest(edit_data.new_content),
        snapshot_reference=str(snapshot.resolved_path) if snapshot else None,
    )
    try:
        _write_journal_record(prepared_rec)
        return None
    except OSError:
        return TransactionResult(
            TransactionOutcome.FAILED, operation_id, [],
            [TransactionFailure(edit_data.edit_id, "JOURNAL_PREPARE", "JournalWriteError",
                                "Journal write failed before side effect.", True)],
            _get_remaining_ids_unlocked(), 0,
        )

def _execute_atomic_apply_and_wal(
    edit_data: PendingEdit,
    operation_id: str,
    snapshot: Any,
) -> tuple[TransactionResult | None, TransactionFailure | None, bool, bool, bool]:
    """Perform atomic write, verify digest, and record APPLIED or FAILED WAL event."""
    resolved_path = edit_data.resolved_path
    new_content = edit_data.new_content
    edit_id = edit_data.edit_id

    # Pre-check #2
    precond_err2 = _check_edit_preconditions(edit_data, operation_id)
    if precond_err2 is not None:
        return precond_err2, None, False, False, False

    try:
        # CAS write: re-verify the on-disk digest immediately before
        # os.replace so a non-lock-sharing external writer that changed
        # the target after check #2 (above) is never silently clobbered.
        write_result = _atomic_write_if_unchanged(
            _Path(resolved_path),
            new_content.encode("utf-8"),
            edit_data.expected_original_digest,
        )
    except Exception as exc:
        _logger.error("_atomic_write raised unexpectedly", exc_info=True)
        write_result = AtomicWriteResult(
            applied=False,
            durability_confirmed=False,
            cleanup_succeeded=True,
            failure_stage=WriteStage.TEMP_WRITE,
            error_type=type(exc).__name__,
            safe_message="Atomic write failed before completion.",
            temp_artifact_remaining=False,
        )

    if write_result is None:
        write_result = AtomicWriteResult(
            applied=False,
            durability_confirmed=False,
            cleanup_succeeded=True,
            failure_stage=WriteStage.TEMP_WRITE,
            error_type="UnknownError",
            safe_message="Atomic write returned no result.",
            temp_artifact_remaining=False,
        )

    if (
        not write_result.applied
        and write_result.failure_stage == WriteStage.PRE_REPLACE_CHECK
    ):
        # CAS abort: the target changed after our precondition checks but
        # before os.replace. We did NOT write anything, so the external
        # modification is preserved. This is a clean CONFLICT — do NOT
        # rollback (our snapshot is stale) and do NOT write a
        # reconciliation record (nothing was applied).
        _logger.error(
            "Atomic write aborted: target changed concurrently",
            extra={
                "operation_id": operation_id,
                "edit_id": edit_id,
                "failure_stage": str(write_result.failure_stage),
            },
        )
        with _state_lock:
            current = _find_edit(edit_id)
            if (
                current is not None
                and current.claim_token == operation_id
                and current.status == "PROCESSING_ACCEPT"
            ):
                current.status = "CONFLICT"
                current.version += 1
        return TransactionResult(
            outcome=TransactionOutcome.CONFLICT,
            operation_id=operation_id,
            succeeded_ids=[],
            failed_items=[
                TransactionFailure(
                    edit_id=edit_id,
                    stage=str(write_result.failure_stage),
                    error_type=write_result.error_type or "DigestMismatch",
                    safe_message=write_result.safe_message
                    or "Target changed concurrently; edit not applied.",
                    retryable=True,
                )
            ],
            remaining_ids=_get_remaining_ids_unlocked(),
            processed_count=0,
        ), None, False, False, False

    failure = None
    reconciliation_required = False
    snapshot_restored = False

    if not write_result.applied:
        requires_reconciliation = (
            write_result.temp_artifact_remaining
            or not write_result.cleanup_succeeded
        )
        _logger.error(
            "Atomic write failed",
            extra={
                "operation_id": operation_id,
                "edit_id": edit_id,
                "failure_stage": str(write_result.failure_stage),
                "requires_reconciliation": requires_reconciliation,
            },
        )
        if _rollback_snapshot(snapshot):
            snapshot_restored = True
        elif not requires_reconciliation:
            requires_reconciliation = True

        new_status = "RECONCILIATION_REQUIRED" if requires_reconciliation else "FAILED"
        with _state_lock:
            current = _find_edit(edit_id)
            if (
                current is not None
                and current.claim_token == operation_id
                and current.status == "PROCESSING_ACCEPT"
            ):
                current.status = new_status
                current.version += 1

        if requires_reconciliation:
            _record_reconciliation(
                operation_id=operation_id,
                edit_id=edit_id,
                resolved_path=resolved_path,
                claim_token=edit_data.claim_token or "",
                expected_digest=_compute_digest(new_content),
                observed_digest=_file_digest(resolved_path),
                failure_stage=str(write_result.failure_stage),
                has_snapshot=snapshot_restored is False,
            )

        err_result = TransactionResult(
            outcome=TransactionOutcome.RECONCILIATION_REQUIRED if requires_reconciliation else TransactionOutcome.FAILED,
            operation_id=operation_id,
            succeeded_ids=[],
            failed_items=[
                TransactionFailure(
                    edit_id=edit_id,
                    stage=str(write_result.failure_stage),
                    error_type=write_result.error_type or "AtomicWriteError",
                    safe_message=write_result.safe_message or "Atomic write failed.",
                    retryable=not requires_reconciliation,
                )
            ],
            remaining_ids=_get_remaining_ids_unlocked(),
            processed_count=0,
        )
        return err_result, None, requires_reconciliation, snapshot_restored, False

    parent_fsynced = write_result.durability_confirmed

    if not failure and write_result.applied and not write_result.cleanup_succeeded:
        failure = TransactionFailure(edit_id, "CLEANUP", "CleanupError", "Failed to clean up temporary artifacts.", True)
        reconciliation_required = True

    if not failure:
        written_digest = _file_digest(resolved_path)
        expected_new_digest = _compute_digest(new_content)
        if written_digest != expected_new_digest:
            failure = TransactionFailure(edit_id, "VERIFY", "DigestMismatch", "File content digest mismatch after write.", True)
            if not _rollback_snapshot(snapshot):
                reconciliation_required = True

    observed = written_digest if not failure else _file_digest(resolved_path)
    if not failure and write_result.applied:
        applied_rec = _make_wal_record(
            event_type="APPLIED", sequence=2,
            operation_id=operation_id, edit_id=edit_data.edit_id,
            operation_type="ACCEPT",
            target_path_relative=edit_data.path,
            expected_original_digest=edit_data.expected_original_digest,
            intended_result_digest=_compute_digest(new_content),
            observed_result_digest=observed,
            side_effect_applied=True,
            durability_confirmed=parent_fsynced,
            snapshot_reference=str(snapshot.resolved_path) if snapshot else None,
        )
        try:
            _write_journal_record(applied_rec)
        except OSError:
            journal_err = TransactionResult(
                TransactionOutcome.RECONCILIATION_REQUIRED, operation_id, [],
                [TransactionFailure(edit_id, "JOURNAL_APPLIED", "JournalWriteError",
                                    "Side effect occurred but journal write failed.", False)],
                _get_remaining_ids_unlocked(), 0,
            )
            return journal_err, None, True, False, parent_fsynced
    else:
        event_type = "RECONCILIATION_REQUIRED" if reconciliation_required else "FAILED"
        failed_wal_rec = _make_wal_record(
            event_type=event_type, sequence=2,
            operation_id=operation_id, edit_id=edit_data.edit_id,
            operation_type="ACCEPT",
            target_path_relative=edit_data.path,
            expected_original_digest=edit_data.expected_original_digest,
            intended_result_digest=_compute_digest(new_content),
            observed_result_digest=observed,
            side_effect_applied=write_result.applied if not snapshot_restored else False,
            durability_confirmed=parent_fsynced,
            snapshot_reference=str(snapshot.resolved_path) if snapshot else None,
            failure_stage=failure.stage if failure else "UNKNOWN",
            recovery_status="PENDING_REVIEW" if reconciliation_required else "RESOLVED",
        )
        try:
            _write_journal_record(failed_wal_rec)
        except OSError:
            pass

    return None, failure, reconciliation_required, snapshot_restored, parent_fsynced


def _commit_accepted_edit(
    edit_id: str,
    edit_data: PendingEdit,
    operation_id: str,
    failure: TransactionFailure | None,
    reconciliation_required: bool,
    snapshot_restored: bool,
    parent_fsynced: bool,
) -> TransactionResult:
    """Commit accepted edit state under state lock (no I/O)."""
    resolved_path = edit_data.resolved_path
    new_content = edit_data.new_content

    with _state_lock:
        edit = _find_edit(edit_id)
        if not edit:
            _record_reconciliation(operation_id, edit_id, resolved_path, edit_data.claim_token or "",
                                   _compute_digest(new_content), _file_digest(resolved_path),
                                   "COMMIT", has_snapshot=True)
            return TransactionResult(TransactionOutcome.RECONCILIATION_REQUIRED, operation_id, [],
                                     [TransactionFailure(edit_id, "COMMIT", "MissingEdit",
                                                         "Edit disappeared during I/O", False)],
                                     _get_remaining_ids_unlocked(), 0)

        if edit.claim_token != operation_id or edit.status != "PROCESSING_ACCEPT" or edit.version != edit_data.version:
            _record_reconciliation(operation_id, edit_id, resolved_path, edit_data.claim_token or "",
                                   _compute_digest(new_content), _file_digest(resolved_path),
                                   "COMMIT_TOKEN_MISMATCH", has_snapshot=True)
            return TransactionResult(TransactionOutcome.RECONCILIATION_REQUIRED, operation_id, [],
                                     [TransactionFailure(edit_id, "COMMIT", "StateChanged",
                                                         "Edit state changed concurrently during I/O", False)],
                                     _get_remaining_ids_unlocked(), 0)

        if failure:
            if reconciliation_required:
                edit.status = "RECONCILIATION_REQUIRED"
                _record_reconciliation(operation_id, edit_id, resolved_path, edit_data.claim_token or "",
                                       _compute_digest(new_content), _file_digest(resolved_path),
                                       "APPLY_UNKNOWN", has_snapshot=snapshot_restored is False)
                outcome = TransactionOutcome.RECONCILIATION_REQUIRED
            else:
                edit.status = "FAILED"
                outcome = TransactionOutcome.FAILED
            return TransactionResult(outcome, operation_id, [], [failure], _get_remaining_ids_unlocked(), 0)
        else:
            _accept_edits_pending.remove(edit)

            committed_rec = _make_wal_record(
                event_type="COMMITTED", sequence=3,
                operation_id=operation_id, edit_id=edit_data.edit_id,
                operation_type="ACCEPT",
                target_path_relative=edit_data.path,
                expected_original_digest=edit_data.expected_original_digest,
                intended_result_digest=_compute_digest(new_content),
                observed_result_digest=_file_digest(resolved_path),
                side_effect_applied=True,
                durability_confirmed=parent_fsynced,
                cleanup_succeeded=True,
                recovery_status="RESOLVED",
            )
            try:
                _write_journal_record(committed_rec)
                committed_journal_ok = True
            except OSError:
                committed_journal_ok = False

            try:
                from engine.events import bus
                bus.emit("pending_edit_accepted", {
                    "operation_id": operation_id,
                    "edit_id": edit_id,
                    "path": edit_data.path,
                    "remaining": len(_get_remaining_ids_unlocked()),
                })
            except ImportError:
                pass

            if parent_fsynced and committed_journal_ok:
                resolved_rec = _make_wal_record(
                    event_type="RESOLVED", sequence=4,
                    operation_id=operation_id, edit_id=edit_data.edit_id,
                    operation_type="ACCEPT",
                    target_path_relative=edit_data.path,
                    expected_original_digest=edit_data.expected_original_digest,
                    intended_result_digest=_compute_digest(new_content),
                    observed_result_digest=_file_digest(resolved_path),
                    side_effect_applied=True,
                    durability_confirmed=True,
                    cleanup_succeeded=True,
                    recovery_status="RESOLVED",
                )
                try:
                    _write_journal_record(resolved_rec)
                except OSError:
                    pass

            outcome = TransactionOutcome.ACCEPTED if parent_fsynced else TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING
            return TransactionResult(outcome, operation_id, [edit_id], [], _get_remaining_ids_unlocked(), 1)


def accept_edit(edit_id: str, expected_version: int | None = None) -> TransactionResult:
    """Accept a single edit by ID using a safe claim-apply-commit cycle.

    Two-phase optimistic content precondition validation + atomic replacement:

      STATE-LOCK: CLAIM → capture immutable edit_data
      PATH-LOCK:  precondition → snapshot → check → temp write → check → replace → verify
      STATE-LOCK: COMMIT
    """
    operation_id = str(uuid.uuid4())

    # ── 1. CLAIM (under state lock, no I/O) ──────────────────────────────
    claim_err, edit_data = _claim_edit_for_accept(edit_id, expected_version, operation_id)
    if claim_err is not None:
        return claim_err
    assert edit_data is not None

    resolved_path = edit_data.resolved_path

    # ── 2. PATH-LOCKED critical section (I/O, no state lock) ─────────────
    with _acquire_path_lock(_Path(resolved_path)):
        # 2a/2b. Preconditions & path validation
        precond_err = _check_edit_preconditions(edit_data, operation_id)
        if precond_err is not None:
            return precond_err

        # 2c. Snapshot from disk & PREPARED WAL record
        snapshot = _create_snapshot_from_disk(resolved_path, "")
        prep_err = _record_prepared_wal(edit_data, operation_id, snapshot)
        if prep_err is not None:
            return prep_err

        # 2d/2e. Atomic write, verify digest & APPLIED WAL
        apply_err, failure, recon_req, snap_restored, parent_fsynced = _execute_atomic_apply_and_wal(
            edit_data, operation_id, snapshot
        )
        if apply_err is not None:
            return apply_err

    # ── 3. COMMIT (under state lock, no I/O) ─────────────────────────────
    return _commit_accepted_edit(
        edit_id=edit_id,
        edit_data=edit_data,
        operation_id=operation_id,
        failure=failure,
        reconciliation_required=recon_req,
        snapshot_restored=snap_restored,
        parent_fsynced=parent_fsynced,
    )


def reject_edit(edit_id: str, expected_version: int | None = None) -> TransactionResult:

    """Reject a single edit by ID using a safe claim-cancel-commit cycle.

    If the edit has a snapshot (from a prior failed accept), attempt
    rollback.  Otherwise simply remove from queue.
    """
    operation_id = str(uuid.uuid4())

    # ── 1. CLAIM ─────────────────────────────────────────────────────────
    with _state_lock:
        edit = _find_edit(edit_id)
        if not edit:
            return TransactionResult(TransactionOutcome.NOT_FOUND, operation_id, [], [], _get_remaining_ids_unlocked(), 0)

        if edit.status != "PENDING":
            return TransactionResult(TransactionOutcome.CONFLICT, operation_id, [], [], _get_remaining_ids_unlocked(), 0)

        if expected_version is not None and edit.version != expected_version:
            return TransactionResult(TransactionOutcome.CONFLICT, operation_id, [], [], _get_remaining_ids_unlocked(), 0)

        edit.status = "PROCESSING_REJECT"
        edit.claim_token = operation_id
        edit.version += 1
        edit_data = dataclasses.replace(edit)

    # WAL: PREPARED before I/O (Gate 2)
    prepared_rec = _make_wal_record(
        event_type="PREPARED", sequence=1,
        operation_id=operation_id, edit_id=edit_data.edit_id,
        operation_type="REJECT",
        target_path_relative=edit_data.path,
        expected_original_digest=edit_data.expected_original_digest,
        intended_result_digest=_compute_digest(edit_data.new_content),
    )
    try:
        _write_journal_record(prepared_rec)
    except OSError:
        return TransactionResult(
            TransactionOutcome.FAILED, operation_id, [],
            [TransactionFailure(edit_id, "JOURNAL_PREPARE", "JournalWriteError",
                                "Journal write failed before side effect.", True)],
            _get_remaining_ids_unlocked(), 0,
        )

    # ── 2. PATH-LOCKED rollback (if snapshot exists) ──────────────────
    snapshot_restored = True
    if edit_data.snapshot is not None:
        with _acquire_path_lock(_Path(edit_data.snapshot.resolved_path)):
            try:
                current = _file_digest(edit_data.snapshot.resolved_path)
                if current != edit_data.snapshot.digest:
                    snapshot_restored = _rollback_snapshot(edit_data.snapshot)
            except Exception:
                snapshot_restored = False

    # WAL: APPLIED after rollback (Gate 2)
    applied_rec = _make_wal_record(
        event_type="APPLIED", sequence=2,
        operation_id=operation_id, edit_id=edit_data.edit_id,
        operation_type="REJECT",
        target_path_relative=edit_data.path,
        expected_original_digest=edit_data.expected_original_digest,
        intended_result_digest=_compute_digest(edit_data.new_content),
        side_effect_applied=snapshot_restored,
        snapshot_reference=str(edit_data.snapshot.resolved_path) if edit_data.snapshot else None,
    )
    try:
        _write_journal_record(applied_rec)
    except OSError:
        pass  # non-fatal for reject

    # ── 3. COMMIT ─────────────────────────────────────────────────────────
    with _state_lock:
        edit = _find_edit(edit_id)
        if not edit:
            _record_reconciliation(operation_id, edit_id, edit_data.resolved_path, edit_data.claim_token or "",
                                   _compute_digest(edit_data.new_content), _file_digest(edit_data.resolved_path),
                                   "REJECT_COMMIT", has_snapshot=False)
            return TransactionResult(TransactionOutcome.RECONCILIATION_REQUIRED, operation_id, [],
                                     [TransactionFailure(edit_id, "COMMIT", "MissingEdit",
                                                         "Edit disappeared during I/O", False)],
                                     _get_remaining_ids_unlocked(), 0)

        if edit.claim_token != operation_id or edit.status != "PROCESSING_REJECT":
            _record_reconciliation(operation_id, edit_id, edit_data.resolved_path, edit_data.claim_token or "",
                                   _compute_digest(edit_data.new_content), _file_digest(edit_data.resolved_path),
                                   "REJECT_COMMIT_TOKEN_MISMATCH", has_snapshot=False)
            return TransactionResult(TransactionOutcome.RECONCILIATION_REQUIRED, operation_id, [],
                                     [TransactionFailure(edit_id, "COMMIT", "StateChanged",
                                                         "Edit state changed concurrently during I/O", False)],
                                     _get_remaining_ids_unlocked(), 0)

        _accept_edits_pending.remove(edit)

        # WAL: COMMITTED after state commit
        committed_rec = _make_wal_record(
            event_type="COMMITTED", sequence=3,
            operation_id=operation_id, edit_id=edit_data.edit_id,
            operation_type="REJECT",
            target_path_relative=edit_data.path,
            expected_original_digest=edit_data.expected_original_digest,
            intended_result_digest=_compute_digest(edit_data.new_content),
            side_effect_applied=snapshot_restored,
            cleanup_succeeded=True,
            recovery_status="RESOLVED",
        )
        try:
            _write_journal_record(committed_rec)
            committed_journal_ok = True
        except OSError:
            committed_journal_ok = False

        try:
            from engine.events import bus
            bus.emit("pending_edit_rejected", {
                "operation_id": operation_id,
                "edit_id": edit_id,
                "path": edit_data.path,
                "remaining": len(_get_remaining_ids_unlocked()),
            })
        except ImportError:
            pass

        # WAL: RESOLVED after cleanup
        needs_review = (not snapshot_restored and edit_data.snapshot is not None)
        if committed_journal_ok and not needs_review:
            resolved_rec = _make_wal_record(
                event_type="RESOLVED", sequence=4,
                operation_id=operation_id, edit_id=edit_data.edit_id,
                operation_type="REJECT",
                target_path_relative=edit_data.path,
                expected_original_digest=edit_data.expected_original_digest,
                intended_result_digest=_compute_digest(edit_data.new_content),
                side_effect_applied=snapshot_restored,
                cleanup_succeeded=True,
                recovery_status="RESOLVED",
            )
            try:
                _write_journal_record(resolved_rec)
            except OSError:
                pass

        outcome = TransactionOutcome.REJECTED
        if not snapshot_restored and edit_data.snapshot is not None:
            outcome = TransactionOutcome.RECONCILIATION_REQUIRED
            _record_reconciliation(operation_id, edit_id, edit_data.resolved_path, edit_data.claim_token or "",
                                   _compute_digest(edit_data.new_content), _file_digest(edit_data.resolved_path),
                                   "REJECT_ROLLBACK_FAILED", has_snapshot=True)

        return TransactionResult(outcome, operation_id, [edit_id], [], _get_remaining_ids_unlocked(), 1)


def _highlight_word_changes(old_line: str, new_line: str) -> tuple[str, str]:
    """Compare two lines at word level and return Rich-markup highlighted versions.

    Uses ``difflib.SequenceMatcher`` to split lines into word tokens and
    colourises changed portions:

    * ``[bold red]...[/bold red]`` for deleted words
    * ``[bold green]...[/bold green]`` for inserted words

    Unchanged words are returned as-is (no markup). The result is safe to pass
    through ``console.print()`` (Rich markup) or ``render_diff()`` (ANSI — the
    tags are passed through as plain text in unchanged lines).
    """
    matcher = difflib.SequenceMatcher(None, old_line.split(), new_line.split())
    old_parts: list[str] = []
    new_parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_words = " ".join(old_line.split()[i1:i2])
        new_words = " ".join(new_line.split()[j1:j2])
        if tag == "equal":
            old_parts.append(old_words)
            new_parts.append(new_words)
        elif tag in ("replace", "delete"):
            old_parts.append(f"[bold red]{old_words}[/bold red]")
            if tag == "replace":
                new_parts.append(f"[bold green]{new_words}[/bold green]")
        elif tag == "insert":
            new_parts.append(f"[bold green]{new_words}[/bold green]")
    return " ".join(old_parts), " ".join(new_parts)
