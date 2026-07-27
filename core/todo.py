from dataclasses import dataclass, field
from enum import Enum
from typing import List, Any, Optional
import re
import time

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
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass
class TodoItem:
    id: int
    text: str
    status: TodoStatus = TodoStatus.PENDING
    verification_note: str = ""  # سبب/دليل الإكمال، مثلاً "py_compile OK, grep clean"
    # ── Evidence-linked fields ──────────────────────────────────────────
    evidence_ids: List[str] = field(default_factory=list)
    completed_at: Optional[float] = None
    completion_source: Optional[str] = None  # "tool_result", "manual", "skipped", "blocked"
    failure_reason: Optional[str] = None

    def __post_init__(self) -> None:
        # Safety net: TodoItem.text must ALWAYS be a str, never a raw dict.
        self.text = _coerce_item_text(self.text)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status.value,
            "verification_note": self.verification_note,
            "evidence_ids": list(self.evidence_ids),
            "completed_at": self.completed_at,
            "completion_source": self.completion_source,
            "failure_reason": self.failure_reason,
        }


class TodoManager:
    """يحتفظ بقائمة المهام لجلسة العمل الحالية. RAM فقط، بدون persistence حاليًا.

    Task-scoping (Phase 2.D):
      - Each plan is bound to a task_id/scope.
      - Switching to a new unrelated task pushes the current plan onto a
        scope stack where it remains preserved but inactive.
      - Explicit "continue"/"resume" restores the previous scope.
      - Old TODOs are NEVER deleted — only scoped out.
    """

    def __init__(self, evidence_log: Any = None) -> None:
        self._items: List[TodoItem] = []
        self._evidence_log = evidence_log
        self._seen_ids: set = set()
        # Phase 2.D: scope stack — preserved plans from previous tasks.
        self._scope_stack: List[List[TodoItem]] = []
        self._current_task_id: Optional[str] = None

    def _emit(self) -> None:
        """Push the current plan to the injected UI bridge (no-op if unset)."""
        get_bridge().on_plan_updated([item.to_dict() for item in self._items])

    def set_evidence_log(self, evidence_log: Any) -> None:
        """Inject an EvidenceLog for cross-referencing TODO completion."""
        self._evidence_log = evidence_log

    def clear(self) -> None:
        """مسح كافة المهام وإعادة التهيئة.

        Note: This is kept for backward compatibility (/clear command).
        For task scoping, use push_scope()/pop_scope() instead.
        """
        self._items.clear()
        self._seen_ids.clear()
        self._emit()

    # ── Phase 2.D: Task scoping ────────────────────────────────────────────

    @property
    def current_task_id(self) -> Optional[str]:
        return self._current_task_id

    def push_scope(self, new_task_id: str) -> None:
        """Save current plan to scope stack and start fresh for a new task.

        The old plan is preserved in the stack; it can be restored later
        via ``pop_scope()``. Old TODOs are NEVER deleted — only scoped out.
        """
        if self._items:
            self._scope_stack.append(list(self._items))
        self._items = []
        self._seen_ids = set()
        self._current_task_id = new_task_id
        self._emit()

    def pop_scope(self) -> bool:
        """Restore the previous scope from the stack.

        Returns True if a scope was restored, False if the stack was empty.
        """
        if not self._scope_stack:
            return False
        self._items = self._scope_stack.pop()
        self._seen_ids.update(item.id for item in self._items)
        self._current_task_id = None
        self._emit()
        return True

    @property
    def has_saved_scope(self) -> bool:
        """True when there is a saved scope that can be restored."""
        return len(self._scope_stack) > 0

    def set_plan(self, texts: List[str]) -> List[TodoItem]:
        """يستبدل القائمة الحالية بخطة جديدة كاملة."""
        self._items = [
            TodoItem(id=i + 1, text=t) for i, t in enumerate(texts)
        ]
        self._seen_ids.update(item.id for item in self._items)
        self._emit()
        return self._items

    def _find_evidence_for_todo(self, todo: TodoItem) -> List[str]:
        """Find evidence record IDs that match a TODO's intent.

        For READ/VERIFY/TEST/EDIT TODOs, looks for successful evidence records
        whose tool and path/action match the TODO's target.
        """
        if self._evidence_log is None:
            return []

        try:
            records = self._evidence_log.get_records()
        except Exception:
            return []

        todo_lower = todo.text.lower()
        # Extract path from TODO text
        path_match = re.search(r'[\w./-]+\.\w{1,6}', todo.text)
        todo_path = path_match.group(0).lower() if path_match else ""

        matching_ids: List[str] = []
        for rec in records:
            if not getattr(rec, "success", False):
                continue

            rec_tool = getattr(rec, "tool", "") or ""
            rec_path = str(getattr(rec, "command_or_path", "") or "").strip().lower()
            rec_action = getattr(rec, "action", "") or ""
            rec_snippet = str(getattr(rec, "output_snippet", "") or "").lower()

            # Path-based match
            if todo_path and rec_path:
                if todo_path in rec_path or rec_path in todo_path:
                    matching_ids.append(getattr(rec, "evidence_id", ""))
                    continue

            # Snippet-based match (evidence mentions the same file)
            if todo_path and todo_path in rec_snippet:
                matching_ids.append(getattr(rec, "evidence_id", ""))
                continue

            # Tool-based match for non-path TODOs
            if not todo_path and rec_tool in todo_lower:
                matching_ids.append(getattr(rec, "evidence_id", ""))
                continue

            # rec_path mentioned in TODO text
            if rec_path and rec_path in todo_lower:
                matching_ids.append(getattr(rec, "evidence_id", ""))
                continue

            # Fallback for generic TODOs (no path, no tool keyword): accept any
            # successful evidence record whose snippet or path appears in the
            # verification context. This prevents false negatives when TODOs
            # have generic text like "Step 1" but the evidence clearly shows
            # a completed action.
            if not todo_path and rec_tool not in todo_lower:
                # Check if the evidence snippet contains meaningful content
                # that could match the TODO's intent
                if rec_snippet and len(rec_snippet) > 5:
                    matching_ids.append(getattr(rec, "evidence_id", ""))
                    continue

        return matching_ids

    def mark_done(self, item_id: int, verification_note: str = "") -> TodoItem:
        item = self._get(item_id)
        if not _is_evidence_note(verification_note, item.text):
            # Rejection: do NOT mark done. Leave the task in_progress and surface
            # a concrete explanation so the caller (tool layer) can relay it as a
            # CONTROL message telling the model what evidence is actually expected.
            item.status = TodoStatus.IN_PROGRESS
            item.completion_source = None
            self._emit()
            raise ValueError(
                f"Cannot mark TODO #{item_id} done: verification_note lacks "
                f"concrete, on-topic evidence. Task was: {item.text!r}. "
                f"Expected a quoted result (command output, a count, a path, or "
                f"'no matches'/'0 errors') that references the same artifact as the "
                f"task — not a vague claim. Got: {verification_note!r}"
            )

        # ── Evidence cross-reference (REQUIRED, not optional) ────────────
        # For EVERY TODO (not just READ/VERIFY/TEST/EDIT), verify that a
        # matching evidence record exists in the EvidenceLog. If no evidence_log
        # is set, this is a hard failure — the production path must always
        # provide an evidence_log.
        if self._evidence_log is None:
            raise ValueError(
                f"Cannot mark TODO #{item_id} done: no evidence_log configured. "
                f"Every mark_done() call requires an evidence_log to cross-reference. "
                f"Task was: {item.text!r}. "
                f"Got verification_note: {verification_note!r}"
            )

        matching_evidence = self._find_evidence_for_todo(item)
        if not matching_evidence:
            # No matching evidence found — do NOT mark done.
            item.status = TodoStatus.IN_PROGRESS
            item.completion_source = None
            self._emit()
            raise ValueError(
                f"Cannot mark TODO #{item_id} done: no matching evidence found "
                f"in EvidenceLog. Task was: {item.text!r}. "
                f"Expected a successful tool result (file_system.read, "
                f"execute_shell, etc.) whose path or output matches the task. "
                f"Got verification_note: {verification_note!r}"
            )

        # ── Test-specific evidence requirement ──────────────────────────
        # If the TODO targets a test/pytest/verify task, the verification_note
        # MUST contain "passed" or "failed" or an explicit exit code.
        _todo_lower = item.text.lower()
        _is_test_task = any(k in _todo_lower for k in ("test", "pytest", "verify", "check"))
        if _is_test_task:
            _note_lower = verification_note.lower()
            if not any(k in _note_lower for k in ("passed", "fail", "error", "exit ")):
                item.status = TodoStatus.IN_PROGRESS
                item.completion_source = None
                self._emit()
                raise ValueError(
                    f"Cannot mark TODO #{item_id} done: test task requires "
                    f"'passed'/'failed'/'error' in verification_note to confirm "
                    f"the test actually ran. Task was: {item.text!r}. "
                    f"Got: {verification_note!r}"
                )

        item.status = TodoStatus.DONE
        item.verification_note = verification_note
        item.evidence_ids = matching_evidence
        item.completed_at = time.time()
        item.completion_source = "tool_result" if matching_evidence else "manual"
        item.failure_reason = None
        self._emit()
        return item

    def mark_skipped(self, item_id: int, reason: str) -> TodoItem:
        """Mark a TODO as skipped with an explicit reason."""
        item = self._get(item_id)
        if not reason or not reason.strip():
            raise ValueError(
                f"Cannot mark TODO #{item_id} skipped: reason is required."
            )
        item.status = TodoStatus.SKIPPED
        item.failure_reason = reason
        item.completion_source = "skipped"
        item.completed_at = time.time()
        self._emit()
        return item

    def mark_blocked(self, item_id: int, reason: str) -> TodoItem:
        """Mark a TODO as blocked with an explicit reason."""
        item = self._get(item_id)
        if not reason or not reason.strip():
            raise ValueError(
                f"Cannot mark TODO #{item_id} blocked: reason is required."
            )
        item.status = TodoStatus.BLOCKED
        item.failure_reason = reason
        item.completion_source = "blocked"
        item.completed_at = time.time()
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
                "evidence_ids": list(item.evidence_ids),
                "completed_at": item.completed_at,
                "completion_source": item.completion_source,
                "failure_reason": item.failure_reason,
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
                evidence_ids=d.get("evidence_ids", []),
                completed_at=d.get("completed_at"),
                completion_source=d.get("completion_source"),
                failure_reason=d.get("failure_reason"),
            )
            for i, d in enumerate(data)
        ]
        self._seen_ids.update(item.id for item in self._items)
        self._emit()
