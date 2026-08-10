from __future__ import annotations

from collections.abc import Iterable

from tools.models import ToolResult


def normalize_action(value: object) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def invalid_action_result(tool_name: str, action: object, allowed_actions: Iterable[str]) -> ToolResult:
    allowed = tuple(allowed_actions)
    allowed_text = ", ".join(repr(item) for item in allowed)
    return ToolResult(
        success=False,
        stderr=(
            f"Error: Invalid action. Tool '{tool_name}' received {action!r}. "
            f"Allowed actions: {allowed_text}."
        ),
        returncode=-1,
        status="invalid_action",
        metadata={"allowed_actions": list(allowed)},
    )


def invalid_action_message(tool_name: str, action: object, allowed_actions: Iterable[str]) -> str:
    return invalid_action_result(tool_name, action, allowed_actions).stderr
