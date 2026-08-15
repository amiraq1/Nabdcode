from __future__ import annotations

from engine.renderer import Renderer, _format_args
from engine.ui_theme import (
    map_tool_to_badge,
    prompt_footer,
    thought_summary,
    workflow_prompt_hint,
)
from ui.cc_style import badge_for_tool, tool_header_line


def test_reference_badges_follow_file_action_and_task_role():
    assert map_tool_to_badge("file_system", {"action": "read"}) == "READ"
    assert map_tool_to_badge("file_system", {"action": "write"}) == "EDIT"
    assert map_tool_to_badge("task", {"role": "review"}) == "TASK"
    assert badge_for_tool("file_system", {"action": "append"})[0] == "EDIT"
    assert badge_for_tool("task", {"role": "research"})[0] == "TASK"


def test_reference_task_header_is_bounded_and_informative():
    detail, extra = _format_args(
        "TASK",
        "task",
        {
            "role": "review",
            "task_id": "review-config",
            "prompt": "Review the configuration and provide evidence-backed findings.",
        },
    )

    assert "review" in detail
    assert "Review the configuration" in detail
    assert extra == "node=review-config"
    assert tool_header_line("task", {"prompt": "Inspect", "role": "research"}).startswith("TASK")


def test_reference_thought_line_is_duration_only_and_collapsible():
    line = thought_summary(1.4)

    assert "Thought for 1 second" in line
    assert "ctrl+o to expand" in line
    assert "reasoning" not in line.lower()


def test_reference_workflow_hints_cover_normal_plan_apply_and_task_summary():
    assert "accept edits" in workflow_prompt_hint("normal")
    assert "plan mode" in workflow_prompt_hint("plan")
    assert "apply mode approved" in workflow_prompt_hint("apply")
    assert "TaskGraph r4" in workflow_prompt_hint("plan", "TaskGraph r4 active=inspect/research")

    apply_footer = prompt_footer(apply_mode=True, task_summary="TaskGraph r4 done=2")
    assert "apply mode approved" in apply_footer
    assert "TaskGraph r4" in apply_footer


def test_renderer_status_snapshot_is_append_only_read_only():
    renderer = Renderer()

    renderer.status_snapshot("Drafting")

    assert renderer._lines
    assert "Drafting" in renderer._lines[-1]


def test_shift_tab_shortcut_changes_real_plan_mode_without_revoking_apply():
    from core.kernel.state import RuntimeState
    from core.plan_apply import APPLY_MODE, PLAN_MODE, current_mode
    from main import toggle_workflow_mode_from_shortcut

    state = RuntimeState("terminal-shortcut")

    assert toggle_workflow_mode_from_shortcut(state) == PLAN_MODE
    assert current_mode(state) == PLAN_MODE
    assert any("[PLAN_APPLY_MODE]" in message.get("content", "") for message in state.get_messages())

    assert toggle_workflow_mode_from_shortcut(state) == "normal"
    assert current_mode(state) == "normal"

    state.operation_mode = APPLY_MODE
    state.apply_authorized_revision = 7
    assert toggle_workflow_mode_from_shortcut(state) == APPLY_MODE
    assert state.apply_authorized_revision == 7
