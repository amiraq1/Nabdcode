"""
_ToolDispatchMixin — consent gates, tool execution, evidence recording.
Extracted from engine/loop.py (refactor _dispatch_and_record_evidence).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from engine.consent import ConsentManager
from engine._loop_helpers import _extract_cmd_or_path
from engine._loop_types import _ToolInteraction
from tools.models import ToolResult
from core.utils import truncate
from core.ui_bridge import get_bridge


class _ToolDispatchMixin:
    """Mixin for ExecutionLoop holding consent, edit-gate, dispatch, and recording.

    Relies on these instance members (set by ExecutionLoop.__init__):
      - self.evidence_log
      - self.state
      - self.max_output_len
      - self._ctx
      - self.dispatcher
      - self.POLL_DELAY
      - self._build_tool_feedback()
    """

    # ------------------------------------------------------------------
    # _dispatch_and_record_evidence — decomposed into 3 focused stages
    # ------------------------------------------------------------------
    def _handle_consent_and_edit_gate(
        self, tool_name: str, tool_args: object
    ) -> bool:
        """Stage 1: Consent Loop + Edit Gateway (human-in-the-loop).

        Returns ``True`` when the call was handled (consent blocked or edit
        rejected/approved) and the caller should return early. Returns ``False``
        when execution should proceed to dispatch.
        """
        # ── Consent Loop (Phase 2 Public Release Protocol) ──────────────────
        if ConsentManager().requires_confirmation(tool_name, tool_args):
            blocked = ConsentManager().confirm(tool_name, tool_args)
            if blocked is not None:
                blocked_rec = self.evidence_log.record(
                    tool=tool_name,
                    command_or_path=_extract_cmd_or_path(tool_args),
                    success=blocked.success,
                    output_snippet=blocked.stdout or blocked.stderr,
                )
                # --- Safe Telemetry Injection (Blocked Tool) ---
                _sys_logger = (
                    getattr(self, "logger", None) or getattr(self, "_logger", None)
                )
                if _sys_logger is None and hasattr(self, "context"):
                    _sys_logger = getattr(self.context, "logger", None)
                elif _sys_logger is None and hasattr(self, "ctx"):
                    _sys_logger = getattr(self.ctx, "logger", None)
                elif _sys_logger is None and hasattr(self, "_ctx") and self._ctx is not None:
                    _sys_logger = getattr(self._ctx, "logger", None)

                if _sys_logger and hasattr(_sys_logger, "log_execution"):
                    _sys_logger.log_execution({
                        "session_id": getattr(self.state, "session_id", "unknown"),
                        "step": getattr(self.state, "step_count", 0),
                        "type": "TOOL_EXECUTION_BLOCKED",
                        "evidence_id": getattr(blocked_rec, "evidence_id", ""),
                        "tool": tool_name,
                        "command_or_path": str(tool_args)[:100],
                        "success": blocked.success,
                        "output_snippet": truncate(
                            blocked.stdout or blocked.stderr or "", 200
                        ),
                    })
                # -------------------------------------------------
                output = truncate(blocked.output or "", self.max_output_len)
                feedback = self._build_tool_feedback(blocked, tool_name, tool_args, output)
                self.state.append_message({
                    "role": "system",
                    "content": f"[TOOL RESULT: {tool_name}]\n{feedback}",
                })
                self.state.increment_step()
                time.sleep(self.POLL_DELAY)
                return True

        # ── Edit Gateway (Phase 2.4) Human-in-the-Loop ──────────────────────
        _is_write = False
        if tool_name in ("edit_file", "replace_file_content"):
            _is_write = True
        elif tool_name == "file_system":
            _action = (
                (tool_args or {}).get("action", "")
                if isinstance(tool_args, dict)
                else ""
            )
            if _action not in ("", "read", "list", "view"):
                _is_write = True

        if _is_write:
            _bridge = get_bridge()
            _approval_event = threading.Event()
            _decision_box: dict[str, bool] = {"approved": False}
            _file_path = str(
                (tool_args if isinstance(tool_args, dict) else {}).get("path")
                or (tool_args if isinstance(tool_args, dict) else {}).get("file", "")
            )
            _diff = str(
                (tool_args if isinstance(tool_args, dict) else {}).get("content")
                or (tool_args if isinstance(tool_args, dict) else {}).get("diff", "")
            )

            _bridge.emit(
                "edit_proposed",
                file=_file_path,
                diff=_diff,
                event=_approval_event,
                decision_box=_decision_box,
            )
            _bridge.emit(
                "status_update", message="⏳ Waiting for human approval to apply edits..."
            )

            # FREEZE the engine thread until the operator responds (120s timeout).
            _approval_event.wait(timeout=120)

            if not _decision_box.get("approved", False):
                _bridge.emit("status_update", message="✋ Edit rejected by user.")
                _result = ToolResult(
                    success=True,
                    stdout="USER REJECTED THE EDIT. Manual override. Please revise your approach.",
                    stderr="",
                    output="USER REJECTED THE EDIT. Manual override. Please revise your approach.",
                )
                self.evidence_log.record(
                    tool=tool_name,
                    command_or_path=_extract_cmd_or_path(tool_args),
                    success=True,
                    output_snippet="Edit rejected by user",
                    action=(
                        str(
                            (tool_args if isinstance(tool_args, dict) else {}).get("action", "")
                        )
                        if isinstance(tool_args, dict)
                        else ""
                    ),
                )
                _output = truncate(_result.output or "", self.max_output_len)
                _feedback = self._build_tool_feedback(_result, tool_name, tool_args, _output)
                self.state.append_message({
                    "role": "system",
                    "content": f"[TOOL RESULT: {tool_name}]\n{_feedback}",
                })
                self.state.increment_step()
                time.sleep(self.POLL_DELAY)
                return True

            _bridge.emit("status_update", message="✅ Edit approved. Applying to disk...")

        return False

    def _execute_and_record(
        self, tool_name: str, tool_args: object
    ) -> tuple[Any, str, Any]:
        """Stage 2: dispatch the tool, record evidence, and inject telemetry.

        Returns ``(result, output, rec)`` — the raw ToolResult, truncated output
        string, and the evidence record.
        """
        # ── todo_write special case ──────────────────────────────────────────
        if (
            tool_name == "todo_write"
            and isinstance(tool_args, dict)
            and tool_args.get("action") == "update"
        ):
            from engine.tool_registry import registry

            _todo_tool = registry.get_tool("todo_write")
            _mgr = (
                getattr(_todo_tool, "_manager", None)
                or getattr(_todo_tool, "todo_manager", None)
            )
            if _mgr is None and hasattr(self, "context") and hasattr(self.context, "todo_manager"):
                _mgr = self.context.todo_manager
            if _mgr is None or len(_mgr.all()) == 0:
                result: Any = ToolResult(
                    success=False,
                    stdout="",
                    stderr=(
                        "Protocol error: call todo_write(action='plan', items=[...]) first."
                    ),
                    returncode=-1,
                )
            else:
                result = self.dispatcher.dispatch(tool_name, tool_args)
        else:
            result = self.dispatcher.dispatch(tool_name, tool_args)

        # ── Evidence Recording ───────────────────────────────────────────────
        cmd_summary = _extract_cmd_or_path(tool_args)
        rec = self.evidence_log.record(
            tool=tool_name,
            command_or_path=cmd_summary,
            success=getattr(result, "success", False),
            output_snippet=(
                getattr(result, "output", "")
                or getattr(result, "stderr", "")
            ),
            action=(
                str(
                    (tool_args if isinstance(tool_args, dict) else {}).get("action", "")
                )
                if isinstance(tool_args, dict)
                else ""
            ),
        )

        # ── Safe Telemetry Injection ─────────────────────────────────────────
        _sys_logger = (
            getattr(self, "logger", None) or getattr(self, "_logger", None)
        )
        if _sys_logger is None and hasattr(self, "context"):
            _sys_logger = getattr(self.context, "logger", None)
        elif _sys_logger is None and hasattr(self, "ctx"):
            _sys_logger = getattr(self.ctx, "logger", None)
        elif _sys_logger is None and hasattr(self, "_ctx") and self._ctx is not None:
            _sys_logger = getattr(self._ctx, "logger", None)

        if _sys_logger and hasattr(_sys_logger, "log_execution"):
            _sys_logger.log_execution({
                "session_id": getattr(self.state, "session_id", "unknown"),
                "step": getattr(self.state, "step_count", 0),
                "type": "TOOL_EXECUTION",
                "evidence_id": getattr(rec, "evidence_id", ""),
                "tool": tool_name,
                "command_or_path": cmd_summary,
                "success": getattr(result, "success", False),
                "output_snippet": truncate(
                    getattr(result, "output", "")
                    or getattr(result, "stderr", "")
                    or "",
                    200,
                ),
            })

        # ── Interaction record for sliding window ────────────────────────────
        output_val = (
            getattr(result, "output", "")
            or getattr(result, "stderr", "")
            or str(result)
        )
        output = truncate(output_val, self.max_output_len)

        ctx = self._ctx
        if ctx is not None:
            latest = (
                self.evidence_log.get_records()[-1]
                if self.evidence_log.get_records()
                else None
            )
            ok = bool(getattr(result, "success", False))
            exit_code = int(getattr(result, "returncode", 0) or 0)
            ctx.tool_interactions.append(_ToolInteraction(
                step=self.state.step_count,
                tool=tool_name,
                ok=ok,
                exit_code=exit_code,
                path_hint=(cmd_summary or "")[:80],
                summary=f"{'SUCCESS' if ok else 'FAILURE'}: {cmd_summary}".strip(),
                output=output,
                evidence_id=latest.evidence_id if latest else "",
                critical=bool(latest.critical) if latest else False,
            ))

        return result, output, rec

    def _finalize_tool_dispatch(
        self,
        tool_name: str,
        tool_args: object,
        result: Any,
        output: str,
        rec: Any,
    ) -> None:
        """Stage 3: build feedback, update state, and sleep.

        This is the terminal action of a successful iteration — no return value.
        """
        feedback = self._build_tool_feedback(result, tool_name, tool_args, output)
        self.state.append_message({
            "role": "system",
            "content": f"[TOOL RESULT: {tool_name}]\n{feedback}",
        })

        # Phase 4.5 — web_search dedup bookkeeping
        if tool_name == "web_search" and isinstance(tool_args, dict):
            raw_query = tool_args.get("query")
            if raw_query:
                norm = str(raw_query).strip().lower()
                ctx = self._ctx
                if ctx is not None:
                    if norm not in ctx.executed_search_queries:
                        ctx.executed_search_queries.append(norm)
                    if getattr(result, "success", False):
                        ctx.last_search_cache[norm] = output

        # Phase 4.5 — reset no-tool counter after a real dispatch
        ctx = self._ctx
        if ctx is not None:
            ctx.consecutive_no_tool_rounds = 0

        self.state.increment_step()
        self.state.prune_history()
        time.sleep(self.POLL_DELAY)

    def _dispatch_and_record_evidence(self, tool_call: Any) -> None:
        """Dispatch the validated tool and log the outcome to the EvidenceLog.

        Chains 3 stages in sequence:
          1. Consent + Edit Gate  → may return early (blocked/rejected)
          2. Execute + Record     → dispatches tool, records evidence
          3. Finalize             → builds feedback, updates state, sleeps
        """
        tool_name = tool_call.tool
        tool_args = tool_call.args

        # Stage 1 — human-in-the-loop gates
        if self._handle_consent_and_edit_gate(tool_name, tool_args):
            return

        # Stage 2 — dispatch + evidence
        result, output, rec = self._execute_and_record(tool_name, tool_args)

        # Stage 3 — feedback + state
        self._finalize_tool_dispatch(tool_name, tool_args, result, output, rec)
