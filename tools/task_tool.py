"""task_tool.py — Subagent delegation tool (OpenCode AgentTool equivalent).

Registers as "task" in the ToolRegistry. When called, spawns a fresh
sub-loop with its own RuntimeState and EvidenceLog (so it never pollutes
the parent agent's context or evidence), runs it with a cheaper model,
and returns the result as structured JSON.

Design notes (adapted to this repo's real contracts):
  * ``ExecutionLoop`` takes ``llm_provider`` (a callable), not ``router``.
    We build a cheap-model provider by forwarding to
    ``execute_agent_with_memory(..., model=<cheap>)``.
  * The sub-loop gets a SEPARATE ``EvidenceLog`` and ``RuntimeState`` — the
    parent's evidence is never touched (hard rule: no pollution).
  * The sub-loop runs in its own daemon thread with a timeout so a runaway
    subagent can't hang the parent. ``_no_stream=True`` keeps it quiet.
  * The convergence gate (>=3 reads) is NOT forced on the subagent: it
    converges on GoalSpec completion. We pass a GoalSpec so the verifier
    gate is satisfied and the loop terminates cleanly.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Optional

from tools.base import BaseTool, BaseModel, Field, ToolResult


class TaskInput(BaseModel):
    prompt: str = Field(..., description="Self-contained task for the subagent")
    role: str = Field(
        "research",
        description=(
            "Delegated role: research, review, or implement. Unknown roles are rejected."
        ),
    )
    task_id: Optional[str] = Field(
        None,
        description=(
            "Optional existing Task Graph node ID. In PLAN mode, a missing ID may create "
            "a read-only delegated node automatically; in APPLY mode it must already exist."
        ),
    )
    model: Optional[str] = Field(
        None, description="Override model for this sub-task (default: cheapest available)"
    )


class TaskTool(BaseTool):
    """Subagent delegation: task(prompt, model?) -> structured result.

    Creates a restricted sub-loop (separate state + evidence), runs it with a
    cheaper model, returns the result and files read. Does NOT pollute the
    parent's context/evidence.
    """

    name = "task"
    description = (
        "Delegate a sub-task to a restricted sub-agent. Use for research, "
        "exploration, or verification without bloating the main context. "
        "Returns a structured summary (result text, files read, tool call count)."
    )

    @property
    def args_schema(self):
        return TaskInput

    def __init__(self, app_context: Any = None, router: Any = None) -> None:
        # app_context/router kept for forward-compat; the tool resolves the
        # live router lazily to avoid import-order cycles at AppContext.build().
        self._ctx = app_context
        self._router = router

    # ── Internal: build a cheaper-model LLM provider callable ────────────

    def _cheap_provider(self, model: Optional[str]):
        from llm_router import execute_agent_with_memory, router as _router

        cheap = model or _router.cheapest_model()

        def _provider(messages: Any, **kwargs: Any) -> str:
            # model kwarg flows through to the provider's payload (overrides
            # the agent's default model). Extra kwargs (logger/tools/etc.) pass
            # through untouched.
            return execute_agent_with_memory(messages, model=cheap, **kwargs)

        return _provider

    def _begin_graph_task(
        self,
        parent_state: Any,
        prompt: str,
        role: str,
        requested_task_id: Optional[str],
    ) -> Optional[str]:
        """Bind one delegated run to the current Task Graph, when present."""
        if parent_state is None:
            return None
        graph = getattr(parent_state, "task_graph", None)
        if graph is None:
            return None

        from core.plan_apply import PLAN_MODE, current_mode, start_task
        from core.task_graph import TaskGraphError

        mode = current_mode(parent_state)
        if mode not in {PLAN_MODE, "apply"}:
            raise TaskGraphError("delegated task requires PLAN or APPLY mode while a Task Graph is active")

        task_id = str(requested_task_id or "").strip()
        if not task_id:
            if mode != PLAN_MODE or role == "implement":
                raise TaskGraphError(
                    "task_id is required for delegated work outside PLAN mode and for implement role"
                )
            sequence = len(graph.tasks()) + 1
            task_id = f"delegated-r{getattr(parent_state, 'plan_revision', 0)}-{sequence}"
            while True:
                try:
                    graph.get_task(task_id)
                except TaskGraphError:
                    break
                sequence += 1
                task_id = f"delegated-r{getattr(parent_state, 'plan_revision', 0)}-{sequence}"
            graph.add_task(
                task_id,
                f"Delegated {role}: {str(prompt).strip()[:240]}",
                role=role,
                plan_revision=getattr(parent_state, "plan_revision", 0),
            )
            parent_state.plan_audit.append(
                {
                    "event": "delegated_task_added",
                    "revision": getattr(parent_state, "plan_revision", 0),
                    "task_id": task_id,
                    "role": role,
                }
            )

        node = start_task(parent_state, task_id, role=role)
        parent_state.plan_audit.append(
            {
                "event": "delegated_task_started",
                "revision": getattr(parent_state, "plan_revision", 0),
                "task_id": node.task_id,
                "role": node.role,
            }
        )
        return node.task_id

    def _fail_graph_task(self, parent_state: Any, task_id: Optional[str], reason: str) -> None:
        if parent_state is None or not task_id:
            return
        from core.plan_apply import fail_task

        try:
            node = fail_task(parent_state, task_id, reason=reason)
            parent_state.plan_audit.append(
                {
                    "event": "delegated_task_failed",
                    "revision": getattr(parent_state, "plan_revision", 0),
                    "task_id": node.task_id,
                    "reason": str(reason)[:300],
                }
            )
        except Exception:
            # The original failure remains authoritative; lifecycle cleanup must
            # never turn a denied/failed delegated call into an exception leak.
            return

    def _complete_graph_task(
        self,
        parent_state: Any,
        task_id: Optional[str],
        evidence_ids: list[str],
    ) -> None:
        if parent_state is None or not task_id:
            return
        from core.plan_apply import complete_task

        node = complete_task(
            parent_state,
            task_id,
            evidence_ids=evidence_ids,
            reason="delegated task completed",
        )
        parent_state.plan_audit.append(
            {
                "event": "delegated_task_completed",
                "revision": getattr(parent_state, "plan_revision", 0),
                "task_id": node.task_id,
                "evidence_ids": list(node.evidence_ids),
            }
        )

    def execute(
        self,
        prompt: str,
        role: str = "research",
        task_id: Optional[str] = None,
        model: Optional[str] = None,
        _parent_state: Any = None,
    ) -> ToolResult:
        """Called by the Dispatcher — transfers to a sub-ExecutionLoop.

        Spawns an isolated sub-agent, waits up to the timeout, and returns a
        structured JSON summary. Never raises into the caller; failures become
        a ToolResult with ``success=False``.
        """
        from engine.subagent_policy import normalize_role
        from engine.subagent_runner import SubagentRunner

        if not prompt or not str(prompt).strip():
            return ToolResult(
                success=False,
                stderr="task tool requires a non-empty 'prompt'.",
                returncode=-1,
                status="error",
            )

        try:
            role = normalize_role(role)
            graph_task_id = self._begin_graph_task(_parent_state, prompt, role, task_id)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(
                success=False,
                stderr=f"Failed to prepare delegated task: {exc}",
                returncode=-1,
                status="policy_denied",
                metadata={"task_graph_task_id": str(task_id or "")},
            )

        try:
            cheap_provider = self._cheap_provider(model)
            runner = SubagentRunner(
                router=cheap_provider,
                max_rounds=5,
                timeout=60,
                role=role,
            )
            result = runner.run(prompt)
        except Exception as exc:  # pragma: no cover - defensive
            failure = f"Delegated task setup failed: {exc}"
            self._fail_graph_task(_parent_state, graph_task_id, failure)
            return ToolResult(
                success=False,
                stderr=failure,
                returncode=-1,
                status="error",
                metadata={"task_graph_task_id": graph_task_id or "", "task_graph_status": "failed"},
            )

        if "error" in result and not result.get("result"):
            failure = str(result.get("error", "Sub-agent failed"))
            self._fail_graph_task(_parent_state, graph_task_id, failure)
            return ToolResult(
                success=False,
                stderr=failure,
                returncode=-1,
                status="error",
                metadata={"task_graph_task_id": graph_task_id or "", "task_graph_status": "failed"},
            )

        evidence_ids = [str(item) for item in result.get("evidence", []) if str(item)]
        if graph_task_id and not evidence_ids:
            failure = "Delegated task returned no evidence; graph completion is denied."
            self._fail_graph_task(_parent_state, graph_task_id, failure)
            return ToolResult(
                success=False,
                stderr=failure,
                returncode=-1,
                status="evidence_missing",
                metadata={"task_graph_task_id": graph_task_id, "task_graph_status": "failed"},
            )
        try:
            self._complete_graph_task(_parent_state, graph_task_id, evidence_ids)
        except Exception as exc:
            failure = f"Task Graph completion denied: {exc}"
            self._fail_graph_task(_parent_state, graph_task_id, failure)
            return ToolResult(
                success=False,
                stderr=failure,
                returncode=-1,
                status="policy_denied",
                metadata={"task_graph_task_id": graph_task_id or "", "task_graph_status": "failed"},
            )

        payload = json.dumps(
            {
                "result": result.get("result", ""),
                "role": result.get("role", role),
                "task_graph_task_id": graph_task_id,
                "task_graph_status": "completed" if graph_task_id else "untracked",
                "files_read": result.get("files_read", []),
                "tool_calls": result.get("tool_calls", 0),
                "evidence_ids": result.get("evidence", []),
            },
            ensure_ascii=False,
        )
        return ToolResult(
            success=True,
            stdout=payload,
            returncode=0,
            status="success",
            metadata={
                "task_graph_task_id": graph_task_id or "",
                "task_graph_status": "completed" if graph_task_id else "untracked",
                "evidence_ids": evidence_ids,
            },
        )
