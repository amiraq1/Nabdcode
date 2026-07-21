from dataclasses import dataclass, field
from enum import Enum
from typing import List, Any
import re

from core.ui_bridge import get_bridge


def _coerce_item_text(item: Any) -> str:
    """Normalize one plan item to a display string.

    The LLM sometimes sends structured objects (e.g.
    {"id": 1, "description": "..."}) instead of the documented list[str].
    Coerce here so no raw dict ever reaches TodoItem.text.
    """
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("description", "content", "text", "task", "title"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return str(item)
    return str(item)


_VAGUE_NOTES = {
    "tested and works", "done", "verified", "completed", "works",
    "ok", "looks good", "confirmed", "success", "passed",
}


def _is_evidence_note(note: str, task_text: str = "") -> bool:
    """A verification_note must quote a CONCRETE observed signal, not a claim.

    Relevance check: if the task names a concrete artifact (e.g. core/loop.py,
    foo.ts, bar.cpp) the note must mention that same artifact — otherwise the
    evidence is off-topic and rejected (e.g. "Found 55 files." for a task that
    asked to read core/loop.py).
    """
    n = (note or "").strip()
    if len(n) < 12 or n.lower() in _VAGUE_NOTES:
        return False
    # Relevance gate: if the task names a concrete artifact (e.g. core/loop.py,
    # foo.ts), the note MUST mention that same artifact (full path OR bare
    # filename). Evaluated first so a generic "Found 55 files." (with a digit)
    # cannot sneak past the numeric heuristic for a specific-file task.
    _artifact = re.search(r"[\w./-]+\.\w{1,6}", task_text or "")
    if _artifact:
        _art = _artifact.group(0).lower()
        _art_base = _art.rsplit("/", 1)[-1]
        if _art not in n.lower() and _art_base not in n.lower():
            return False
    if re.search(r"\d", n):              # a count/line/exit code
        return True
    if re.search(r"[/.]\w", n):          # a path or file.ext
        return True
    if any(q in n for q in ("'", '"', "`")):  # a quoted token/command
        return True
    lowered = n.lower()
    return any(k in lowered for k in (
        "no match", "no error", "0 error", "exit", "grep",
        "compile", "output", "pass", "fail",
    ))


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class TodoItem:
    id: int
    text: str
    status: TodoStatus = TodoStatus.PENDING
    verification_note: str = ""  # سبب/دليل الإكمال، مثلاً "py_compile OK, grep clean"

    def __post_init__(self) -> None:
        # Safety net: TodoItem.text must ALWAYS be a str, never a raw dict.
        self.text = _coerce_item_text(self.text)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status.value,
            "verification_note": self.verification_note,
        }


class TodoManager:
    """يحتفظ بقائمة المهام لجلسة العمل الحالية. RAM فقط، بدون persistence حاليًا."""

    def __init__(self) -> None:
        self._items: List[TodoItem] = []

    def _emit(self) -> None:
        """Push the current plan to the injected UI bridge (no-op if unset)."""
        get_bridge().on_plan_updated([item.to_dict() for item in self._items])

    def clear(self) -> None:
        """مسح كافة المهام وإعادة التهيئة."""
        self._items.clear()
        self._emit()

    def set_plan(self, texts: List[str]) -> List[TodoItem]:
        """يستبدل القائمة الحالية بخطة جديدة كاملة."""
        self._items = [
            TodoItem(id=i + 1, text=t) for i, t in enumerate(texts)
        ]
        self._emit()
        return self._items

    def mark_done(self, item_id: int, verification_note: str = "") -> TodoItem:
        item = self._get(item_id)
        if not _is_evidence_note(verification_note, item.text):
            # Rejection: do NOT mark done. Leave the task in_progress and surface
            # a concrete explanation so the caller (tool layer) can relay it as a
            # CONTROL message telling the model what evidence is actually expected.
            item.status = TodoStatus.IN_PROGRESS
            self._emit()
            raise ValueError(
                f"Cannot mark TODO #{item_id} done: verification_note lacks "
                f"concrete, on-topic evidence. Task was: {item.text!r}. "
                f"Expected a quoted result (command output, a count, a path, or "
                f"'no matches'/'0 errors') that references the same artifact as the "
                f"task — not a vague claim. Got: {verification_note!r}"
            )
        item.status = TodoStatus.DONE
        item.verification_note = verification_note
        self._emit()
        return item

    def mark_in_progress(self, item_id: int) -> TodoItem:
        item = self._get(item_id)
        item.status = TodoStatus.IN_PROGRESS
        self._emit()
        return item

    def _get(self, item_id: int) -> TodoItem:
        # Tool args may arrive as text ("1") from the LLM — normalize to int,
        # otherwise  item.id == item_id  becomes  1 == "1"  = False and fails silently.
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            raise KeyError(f"TODO item #{item_id!r} not found (invalid id)")
        for item in self._items:
            if item.id == item_id:
                return item
        raise KeyError(
            f"TODO item #{item_id} not found. "
            f"You must call todo_write(action='plan', items=[...]) "
            f"before using action='update'. "
            f"Current items: {len(self._items)}"
        )

    def all(self) -> List[TodoItem]:
        return list(self._items)

    def to_serializable(self) -> List[dict]:
        return [
            {
                "id": item.id,
                "text": item.text,
                "status": item.status.value,
                "verification_note": item.verification_note,
            }
            for item in self._items
        ]

    def restore(self, data: List[dict]) -> None:
        self._items = [
            TodoItem(
                id=d.get("id", i + 1),
                text=d.get("text", ""),
                status=TodoStatus(d.get("status", TodoStatus.PENDING.value)),
                verification_note=d.get("verification_note", ""),
            )
            for i, d in enumerate(data)
        ]
        self._emit()
