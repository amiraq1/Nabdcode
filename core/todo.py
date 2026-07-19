from dataclasses import dataclass, field
from enum import Enum
from typing import List

from core.ui_bridge import get_bridge


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
        if not verification_note:
            raise ValueError(
                f"Cannot mark TODO #{item_id} done without a verification_note"
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
        raise KeyError(f"TODO item #{item_id} not found")

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
