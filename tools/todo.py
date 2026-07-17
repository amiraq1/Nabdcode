from __future__ import annotations

from typing import Any, Optional, Type

from tools.base import BaseTool, BaseModel
from tools.models import ToolResult
from core.todo import TodoManager, TodoStatus


class TodoWriteArgs(BaseModel):
    action: str = ""
    items: Optional[list[str]] = None
    item_id: Optional[int] = None
    status: Optional[str] = None
    verification_note: Optional[str] = None


class TodoWriteTool(BaseTool):
    """
    Creates or updates the TODO plan. Two modes:
    - action="plan": pass `items` (list[str]) to set the full plan.
    - action="update": pass `item_id` + `status` (+ `verification_note` if status=done).
    """

    name = "todo_write"

    description: str = (
        "Create or update the TODO plan for the current session. "
        "Use action='plan' with a list of items to set the full plan, "
        "or action='update' with item_id and status (pending/in_progress/done) "
        "to update a single item. When marking done, a verification_note is required."
    )

    def __init__(self, todo_manager: TodoManager):
        self._manager = todo_manager

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return TodoWriteArgs

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")

        if not isinstance(action, str):
            return ToolResult(
                success=False,
                stderr="Missing or invalid 'action'.",
                returncode=-1,
            )

        try:
            if action == "plan":
                items = kwargs.get("items")
                if not items or not isinstance(items, list):
                    return ToolResult(
                        success=False,
                        stderr="`items` (list[str]) is required for action=plan.",
                        returncode=-1,
                    )
                todos = self._manager.set_plan(items)
                return ToolResult(
                    success=True,
                    stdout=f"Plan created with {len(todos)} items.",
                )

            if action == "update":
                item_id = kwargs.get("item_id")
                status = kwargs.get("status")

                if item_id is None or status is None:
                    return ToolResult(
                        success=False,
                        stderr="`item_id` and `status` are required for action=update.",
                        returncode=-1,
                    )

                if status == TodoStatus.DONE.value:
                    verification_note = kwargs.get("verification_note", "")
                    item = self._manager.mark_done(item_id, verification_note)
                elif status == TodoStatus.IN_PROGRESS.value:
                    item = self._manager.mark_in_progress(item_id)
                else:
                    return ToolResult(
                        success=False,
                        stderr=f"Unknown status: {status}",
                        returncode=-1,
                    )

                return ToolResult(
                    success=True,
                    stdout=f"TODO #{item.id} → {item.status.value}",
                )

            return ToolResult(
                success=False,
                stderr=f"Unknown action: {action}",
                returncode=-1,
            )

        except (ValueError, KeyError) as e:
            return ToolResult(
                success=False,
                stderr=str(e),
                returncode=-1,
            )
