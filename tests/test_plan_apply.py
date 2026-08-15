"""Regression tests for explicit Plan/Apply execution policy."""

from __future__ import annotations

from types import SimpleNamespace

from core.command_dispatcher import process_slash_command
from core.evidence import EvidenceLog
from core.diff_review import approve_review, build_review, store_review
from core.kernel.state import RuntimeState
from core.plan_apply import (
    APPLY_MODE,
    NORMAL_MODE,
    PLAN_MODE,
    apply_is_authorized,
    authorize_apply,
    enter_plan_mode,
    plan_mode_block_reason,
    record_plan,
    runtime_tool_block_reason,
)
from engine._dispatch import _ToolDispatchMixin
from tools.models import ToolResult


def _approve_current_review(state: RuntimeState) -> None:
    store_review(state, build_review(state))
    ok, message = approve_review(state)
    assert ok is True, message


def test_plan_mode_is_allowlist_based_for_tools() -> None:
    state = RuntimeState("plan-policy")
    enter_plan_mode(state)

    assert plan_mode_block_reason("file_system", {"action": "read"}, state) is None
    assert plan_mode_block_reason("code_intelligence", {"action": "list_symbols"}, state) is None
    assert plan_mode_block_reason("todo_write", {"action": "plan", "items": ["Inspect"]}, state) is None

    assert "blocks" in plan_mode_block_reason("execute_shell", {"command": "pwd"}, state)
    assert "blocks" in plan_mode_block_reason("edit_file", {"path": "a.py"}, state)
    assert "blocks" in plan_mode_block_reason("task", {"prompt": "delegate"}, state)
    assert "read-only" in plan_mode_block_reason("file_system", {"action": "write"}, state)


def test_apply_requires_recorded_plan_and_is_revision_bound() -> None:
    state = RuntimeState("plan-revision")

    ok, message = authorize_apply(state)
    assert ok is False
    assert "No recorded plan" in message
    assert state.operation_mode == NORMAL_MODE

    enter_plan_mode(state)
    assert record_plan(state, ["Inspect module", "Propose diff"]) == 1
    _approve_current_review(state)
    ok, _ = authorize_apply(state)
    assert ok is True
    assert state.operation_mode == APPLY_MODE
    assert apply_is_authorized(state) is True

    # A revised plan revokes approval and returns the workflow to review state.
    assert record_plan(state, ["Inspect module", "Propose safer diff"]) == 2
    assert apply_is_authorized(state) is False
    assert state.apply_authorized_revision == 0
    assert "not authorized" in runtime_tool_block_reason(
        "execute_shell", {"command": "echo stale"}, state
    )
    assert state.plan_audit[-1]["event"] == "plan_recorded"


def test_clear_context_resets_plan_apply_state() -> None:
    state = RuntimeState("plan-clear")
    enter_plan_mode(state)
    record_plan(state, ["Inspect"])
    authorize_apply(state)

    state.clear_context()

    assert state.operation_mode == NORMAL_MODE
    assert state.plan_revision == 0
    assert state.plan_items == ()
    assert state.apply_authorized_revision == 0
    assert state.plan_audit == []


def test_explicit_slash_commands_drive_state_and_prompt(capsys) -> None:
    state = RuntimeState("plan-commands")
    ctx = SimpleNamespace()

    assert process_slash_command("/plan", state, ctx, "base") is True
    assert state.operation_mode == PLAN_MODE
    assert "PLAN MODE" in state.get_last_message()["content"]

    assert process_slash_command("/apply", state, ctx, "base") is True
    assert state.operation_mode == PLAN_MODE
    assert "APPLY refused" in capsys.readouterr().out

    record_plan(state, ["Read the target file"])
    assert process_slash_command("/review run", state, ctx, "base") is True
    assert process_slash_command("/review approve", state, ctx, "base") is True
    assert process_slash_command("/apply", state, ctx, "base") is True
    assert state.operation_mode == APPLY_MODE
    assert apply_is_authorized(state) is True
    assert "APPLY MODE" in state.get_last_message()["content"]
    mode_messages = [
        message["content"]
        for message in state.get_messages()
        if message.get("content", "").startswith("[PLAN_APPLY_MODE]")
    ]
    assert len(mode_messages) == 1
    assert "APPLY MODE" in mode_messages[0]


class _PlanGateHarness(_ToolDispatchMixin):
    """Minimal loop surface proving the central pre-dispatch policy gate."""

    POLL_DELAY = 0
    max_output_len = 400

    def __init__(self) -> None:
        self.state = RuntimeState("plan-gate")
        self.evidence_log = EvidenceLog()
        self.dispatcher = SimpleNamespace(
            dispatch=lambda tool_name, tool_args: ToolResult(success=True, stdout="ok")
        )
        self._ctx = None

    def _build_tool_feedback(self, result, tool_name, tool_args, output):
        return output


def test_dispatch_gate_blocks_side_effect_before_consent_or_dispatch() -> None:
    harness = _PlanGateHarness()
    enter_plan_mode(harness.state)

    handled = harness._handle_consent_and_edit_gate(
        "execute_shell", {"command": "touch should-not-run"}
    )

    assert handled is True
    assert harness.state.get_last_message()["role"] == "system"
    assert "PLAN MODE blocks" in harness.state.get_last_message()["content"]
    record = harness.evidence_log.get_records()[-1]
    assert record.success is False
    assert record.tool == "execute_shell"


def test_dispatch_gate_leaves_read_only_call_for_normal_dispatch() -> None:
    harness = _PlanGateHarness()
    enter_plan_mode(harness.state)

    handled = harness._handle_consent_and_edit_gate(
        "file_system", {"action": "read", "path": "README.md"}
    )

    assert handled is False


def test_dispatch_records_todo_plan_as_a_revision() -> None:
    harness = _PlanGateHarness()
    enter_plan_mode(harness.state)
    args = {"action": "plan", "items": ["Inspect config", "Write tests"]}

    result, _, _ = harness._execute_and_record("todo_write", args)

    assert result.success is True
    assert result.metadata["plan_revision"] == 1
    assert harness.state.plan_items == ("Inspect config", "Write tests")
    _approve_current_review(harness.state)
    ok, _ = authorize_apply(harness.state)
    assert ok is True
