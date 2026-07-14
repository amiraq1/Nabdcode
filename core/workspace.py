"""core/workspace.py — Workspace Context Loader (AGENTS.md awareness).

Gives the agent project-specific instructions by scanning the current working
directory for an ``AGENTS.md`` file (or a ``.agents/config.md`` fallback) and
returning its (size-capped, sanitized) contents. The result is meant to be
injected into the system prompt inside ``<workspace_context>`` XML guards so the
Phase 4 compaction engine treats it as an instruction-anchor (messages[0]) rather
than evictable tool history.

All failures are fail-safe: a missing file, an unreadable file, or a permission
error yields an empty string — never an exception, never a crash.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

# Hard cap (bytes) on the workspace context we will ingest. Prevents an
# accidentally huge AGENTS.md from overflowing the context window. 10KB is
# generous for instruction text and keeps the system anchor compact.
MAX_WORKSPACE_CONTEXT_BYTES: int = 10 * 1024

# Candidate locations, checked in priority order. Relative paths are resolved
# against cwd; the .agents/ variant is the namespaced fallback so unrelated
# tooling's AGENTS.md does not collide with NABD's own repo-level file.
_CANDIDATE_RELATIVE: List[str] = [
    "AGENTS.md",
    ".agents/config.md",
]


def load_workspace_context(cwd: Path) -> str:
    """Load project-specific instructions for *cwd*.

    Scans for ``AGENTS.md`` then ``.agents/config.md``. Returns the (sanitized,
    size-capped) file contents, or ``""`` if none exists / cannot be read.
    Permission errors and oversized files are handled gracefully (fail-safe).
    """
    root = Path(cwd)

    chosen: Path | None = None
    for rel in _CANDIDATE_RELATIVE:
        candidate = root / rel
        if candidate.is_file():
            chosen = candidate
            break

    if chosen is None:
        # No workspace instruction file present — fail silently.
        return ""

    try:
        raw = chosen.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError, UnicodeDecodeError):
        # Unreadable / no permission → fail-safe to empty context.
        return ""

    # Hard size limit: truncate at MAX bytes. We work in characters (UTF-8) and
    # avoid splitting mid-code-point by slicing on the decoded string. The cap
    # is conservative; instruction text rarely approaches it.
    if len(raw) > MAX_WORKSPACE_CONTEXT_BYTES:
        raw = raw[:MAX_WORKSPACE_CONTEXT_BYTES]

    # Sanitize untrusted file content the same way other external data is
    # scrubbed before it enters the model's context channel.
    try:
        from core.sanitize import sanitize
        return sanitize(raw)
    except Exception:
        # sanitize should never fail, but stay fail-safe regardless.
        return raw
