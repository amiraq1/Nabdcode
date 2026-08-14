"""core/kernel/collapse.py — Pure collapse block storage.

Decoupled leaf node in core/kernel/ — zero UI dependencies.
Provides storage for collapsed output blocks by ID.
"""

from __future__ import annotations

from typing import Sequence


class CollapseStore:
    """Store collapsed output blocks by id so they can be expanded later.

    ``store()`` returns an integer id; ``expand(id)`` returns the original
    lines (a fresh list copy) or ``None`` for an unknown/expired id.
    """

    def __init__(self) -> None:
        self._blocks: dict[int, list[str]] = {}
        self._next_id: int = 1

    def store(self, lines: Sequence[str]) -> int:
        """Store *lines* and return its id."""
        cid = self._next_id
        self._next_id += 1
        self._blocks[cid] = list(lines)
        return cid

    def expand(self, cid: int) -> list[str] | None:
        """Return a copy of the stored block, or None if unknown."""
        block = self._blocks.get(cid)
        if block is None:
            return None
        return list(block)

    def ids(self) -> list[int]:
        """Return all stored ids (ascending)."""
        return sorted(self._blocks)


# Process-wide collapse store: /expand and future ctrl+o share it.
collapse_store = CollapseStore()
