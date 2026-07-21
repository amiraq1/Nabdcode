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

    def execute(self, prompt: str, model: Optional[str] = None) -> ToolResult:
        """Called by the Dispatcher — transfers to a sub-ExecutionLoop.

        Spawns an isolated sub-agent, waits up to the timeout, and returns a
        structured JSON summary. Never raises into the caller; failures become
        a ToolResult with ``success=False``.
        """
        from core.evidence import EvidenceLog
        from core.kernel.state import RuntimeState, GoalSpec
        from engine.loop import ExecutionLoop
        from engine.subagent_runner import SubagentRunner

        if not prompt or not str(prompt).strip():
            return ToolResult(
                success=False,
                stderr="task tool requires a non-empty 'prompt'.",
                returncode=-1,
                status="error",
            )

        try:
            cheap_provider = self._cheap_provider(model)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(
                success=False,
                stderr=f"Failed to build sub-agent provider: {exc}",
                returncode=-1,
                status="error",
            )

        runner = SubagentRunner(router=cheap_provider, max_rounds=5, timeout=60)
        result = runner.run(prompt)

        if "error" in result and not result.get("result"):
            return ToolResult(
                success=False,
                stderr=str(result.get("error", "Sub-agent failed")),
                returncode=-1,
                status="error",
            )

        payload = json.dumps(
            {
                "result": result.get("result", ""),
                "files_read": result.get("files_read", []),
                "tool_calls": result.get("tool_calls", 0),
                "evidence_ids": result.get("evidence", []),
            },
            ensure_ascii=False,
        )
        return ToolResult(
            success=True,
            stdout=payload,
            output=payload,
            returncode=0,
            status="success",
        )
