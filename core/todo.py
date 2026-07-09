from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


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


class TodoManager:
    """يحتفظ بقائمة المهام لجلسة العمل الحالية."""

    def __init__(self) -> None:
        self._items: List[TodoItem] = []

    def set_plan(self, texts: List[str]) -> List[TodoItem]:
        """يستبدل القائمة الحالية بخطة جديدة كاملة."""
        self._items = [
            TodoItem(id=i + 1, text=t) for i, t in enumerate(texts)
        ]
        return self._items

    def mark_done(self, item_id: int, verification_note: str = "") -> TodoItem:
        item = self._get(item_id)
        if not verification_note:
            raise ValueError(
                f"Cannot mark TODO #{item_id} done without a verification_note"
            )
        item.status = TodoStatus.DONE
        item.verification_note = verification_note
        return item

    def mark_in_progress(self, item_id: int) -> TodoItem:
        item = self._get(item_id)
        item.status = TodoStatus.IN_PROGRESS
        return item

    def _get(self, item_id: int) -> TodoItem:
        for item in self._items:
            if item.id == item_id:
                return item
        raise KeyError(f"TODO item #{item_id} not found")

    def all(self) -> List[TodoItem]:
        return list(self._items)

    # ── Serialization ────────────────────────────────────────────────────

    def to_serializable(self) -> List[Dict[str, Any]]:
        """Serialize all items to JSON-safe dicts."""
        return [
            {
                "id": item.id,
                "text": item.text,
                "status": item.status.value,
                "verification_note": item.verification_note,
            }
            for item in self._items
        ]

    def restore(self, items: List[Dict[str, Any]]) -> None:
        """Replace all items from previously serialized dicts."""
        self._items = [
            TodoItem(
                id=it["id"],
                text=it["text"],
                status=TodoStatus(it["status"]),
                verification_note=it.get("verification_note", ""),
            )
            for it in items
        ]
