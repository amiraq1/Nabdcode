"""Explicit Plan/Apply workflow and runtime policy for Nabdcode.

The workflow is deliberately stateful and enforced at the tool-dispatch choke
point.  A prompt instruction may guide a model, but this module is the source
of truth that prevents a plan-only turn from mutating the workspace.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

NORMAL_MODE = "normal"
PLAN_MODE = "plan"
APPLY_MODE = "apply"
_VALID_MODES = frozenset({NORMAL_MODE, PLAN_MODE, APPLY_MODE})
_MODE_CONTEXT_PREFIX = "[PLAN_APPLY_MODE]"

PLAN_MODE_INSTRUCTION = """[PLAN_APPLY_MODE] You are in explicit PLAN MODE.

The runtime permits only workspace exploration and `todo_write(action='plan')`.
Do not attempt shell execution, file writes, external side effects, or nested
delegation. Inspect the workspace, create a concise ordered TODO plan, explain
risks and verification steps, then ask the operator to run `/apply`.
"""

APPLY_MODE_INSTRUCTION = """[PLAN_APPLY_MODE] You are in explicit APPLY MODE.

The operator approved the current recorded plan. Execute only the approved
work, keep TODO status current, and rely on the existing consent and edit
approval gates for every sensitive action. If the plan must materially change,
stop and ask the operator to return to `/plan` and approve a new revision.
"""

_READ_ONLY_FILE_ACTIONS = frozenset({"read", "read_many", "list", "view"})
_PLAN_SAFE_TOOLS = frozenset({"code_intelligence", "search_memory", "web_search"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def synchronize_mode_context(state: Any, instruction: str | None) -> None:
    """Replace the transient Plan/Apply system instruction in conversation state.

    The prompt sees exactly one mode contract at a time.  This avoids leaving a
    stale PLAN instruction in context after `/apply`, while preserving all user
    messages and the base system instruction.
    """
    messages = list(getattr(state, "get_messages", lambda: [])())
    retained = [
        message
        for message in messages
        if not str(message.get("content", "")).startswith(_MODE_CONTEXT_PREFIX)
    ]
    if instruction:
        retained.append({"role": "system", "content": instruction})
    if hasattr(state, "set_messages"):
        state.set_messages(retained)


def current_mode(state: Any) -> str:
    """Return a supported mode; treat invalid or legacy values as normal."""
    mode = str(getattr(state, "operation_mode", NORMAL_MODE) or NORMAL_MODE).lower()
    return mode if mode in _VALID_MODES else NORMAL_MODE


def _set_mode(state: Any, mode: str) -> None:
    if mode not in _VALID_MODES:
        raise ValueError(f"Unsupported Plan/Apply mode: {mode}")
    state.operation_mode = mode
    state.plan_mode_changed_at = _now()


def enter_plan_mode(state: Any) -> None:
    """Enter read-only planning and revoke approval for any prior plan."""
    _set_mode(state, PLAN_MODE)
    state.apply_authorized_revision = 0
    state.review_revision = 0
    state.review_report = {}
    state.review_test_status = "not_run"
    state.review_approved_revision = 0


def return_to_normal_mode(state: Any) -> None:
    """Leave the explicit workflow without deleting the recorded plan."""
    _set_mode(state, NORMAL_MODE)
    state.apply_authorized_revision = 0
    state.review_revision = 0
    state.review_report = {}
    state.review_test_status = "not_run"
    state.review_approved_revision = 0


def record_plan(state: Any, items: Iterable[object]) -> int:
    """Store a new plan revision and invalidate prior Apply authorization."""
    clean_items = tuple(str(item).strip() for item in items if str(item).strip())
    if not clean_items:
        raise ValueError("A Plan/Apply plan must contain at least one non-empty item.")

    revision = int(getattr(state, "plan_revision", 0) or 0) + 1
    state.plan_revision = revision
    state.plan_items = clean_items
    # A plan revision owns exactly one graph. Replacing it prevents stale task
    # nodes from being executed after the operator records a new plan.
    from core.task_graph import TaskGraph
    state.task_graph = TaskGraph(plan_revision=revision)
    state.apply_authorized_revision = 0
    state.review_revision = 0
    state.review_report = {}
    state.review_test_status = "not_run"
    state.review_approved_revision = 0
    state.plan_audit.append(
        {
            "event": "plan_recorded",
            "revision": revision,
            "items": list(clean_items),
            "timestamp": _now(),
        }
    )
    return revision


def authorize_apply(state: Any) -> tuple[bool, str]:
    """Approve the current recorded plan and enter Apply mode.

    Authorization is revision-bound.  Recording another plan automatically
    invalidates it, so an old `/apply` cannot approve a changed plan.
    """
    revision = int(getattr(state, "plan_revision", 0) or 0)
    if revision <= 0 or not tuple(getattr(state, "plan_items", ()) or ()):
        return False, "No recorded plan exists. Run `/plan`, create a TODO plan, then retry `/apply`."

    from core.diff_review import review_is_approved
    if not review_is_approved(state):
        return False, "Current plan has no approved diff/test review. Run `/review run`, inspect it, then `/review approve`."

    _set_mode(state, APPLY_MODE)
    state.apply_authorized_revision = revision
    state.plan_audit.append(
        {
            "event": "apply_authorized",
            "revision": revision,
            "timestamp": _now(),
        }
    )
    return True, f"Apply mode authorized for plan revision {revision}."


def apply_is_authorized(state: Any) -> bool:
    revision = int(getattr(state, "plan_revision", 0) or 0)
    return current_mode(state) == APPLY_MODE and revision > 0 and int(
        getattr(state, "apply_authorized_revision", 0) or 0
    ) == revision


def plan_status(state: Any) -> dict[str, object]:
    """Return a JSON-friendly snapshot suitable for commands and UI surfaces."""
    return {
        "mode": current_mode(state),
        "revision": int(getattr(state, "plan_revision", 0) or 0),
        "items": list(getattr(state, "plan_items", ()) or ()),
        "apply_authorized": apply_is_authorized(state),
        "review_status": str(getattr(state, "review_test_status", "not_run")),
        "review_approved": bool(getattr(state, "review_approved_revision", 0)) == int(getattr(state, "plan_revision", 0) or 0) and int(getattr(state, "plan_revision", 0) or 0) > 0,
        "task_graph": (
            getattr(state, "task_graph", None).to_dict()
            if getattr(state, "task_graph", None) is not None
            else None
        ),
    }


def plan_mode_block_reason(tool_name: str, tool_args: object, state: Any) -> str | None:
    """Return a deny reason when a call is not allowed during PLAN mode.

    The policy is allowlist-based.  Unknown tools are blocked by default, which
    keeps future integrations from accidentally inheriting mutation access.
    """
    if current_mode(state) != PLAN_MODE:
        return None

    args = tool_args if isinstance(tool_args, dict) else {}
    if tool_name == "todo_write":
        if args.get("action") == "plan":
            return None
        return "PLAN MODE permits only todo_write(action='plan'); status updates belong to Apply mode."

    if tool_name == "file_system":
        action = str(args.get("action", "")).lower()
        if action in _READ_ONLY_FILE_ACTIONS:
            return None
        return f"PLAN MODE blocks file_system(action='{action or 'unknown'}'); exploration is read-only."

    if tool_name in _PLAN_SAFE_TOOLS:
        return None

    return f"PLAN MODE blocks '{tool_name}'. Record a plan and use `/apply` before executing side effects."


def runtime_tool_block_reason(tool_name: str, tool_args: object, state: Any) -> str | None:
    """Apply the Plan/Apply state machine to a pending tool call.

    After a new plan revision is recorded, the old Apply authorization becomes
    invalid.  The runtime then returns to a review-only posture until the
    operator explicitly approves the new revision with `/apply`.
    """
    plan_reason = plan_mode_block_reason(tool_name, tool_args, state)
    if plan_reason:
        return plan_reason

    if current_mode(state) == APPLY_MODE:
        from core.diff_review import review_is_approved
        if not review_is_approved(state):
            return "APPLY MODE is not authorized: an approved diff/test review is required for the current plan revision."
        if not apply_is_authorized(state):
            return (
                "APPLY MODE is not authorized for the current plan revision. "
                "Review the updated plan and run `/apply` again before tool execution."
            )
    return None


def reset_plan_apply(state: Any) -> None:
    """Reset explicit workflow state when a session is cleared."""
    state.operation_mode = NORMAL_MODE
    state.plan_revision = 0
    state.plan_items = ()
    state.apply_authorized_revision = 0
    state.review_revision = 0
    state.review_report = {}
    state.review_test_status = "not_run"
    state.review_approved_revision = 0
    state.plan_mode_changed_at = _now()
    state.plan_mode_changed_at = _now()
