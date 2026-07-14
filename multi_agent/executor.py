from __future__ import annotations

import uuid
from engine.deep_agent import NativeDeepAgent
from engine.state import RuntimeState
from core.memory import load_memory
from core.monitoring import EventLogger


class ExecutorAgent:
    """Executor agent running a single verifiable subtask."""

    def __init__(self, memory: str | None = None):
        self.memory = memory if memory is not None else load_memory()
        self.agent = NativeDeepAgent(RuntimeState(session_id=f"exec-{uuid.uuid4().hex}"))

    def run_single(self, subtask: str) -> tuple[str, str]:
        prompt = subtask
        EventLogger.log("executor", "tool_call", "info", tool="run_single", task=subtask[:60])
        if self.memory:
            prompt = f"# Previous Memory:\n{self.memory}\n\nTask: {subtask}"
        output = self.agent.run(prompt)
        evidence_parts = [
            r.output_snippet
            for r in self.agent.evidence_log._records.values()
            if r.success
        ]
        evidence = " ".join(evidence_parts)
        if not evidence:
            evidence = str(output)
        EventLogger.log("executor", "run_done", "done", task=subtask[:60])
        return str(output), evidence

    def retry_with_critique(self, subtask: str, critique: str) -> tuple[str, str]:
        EventLogger.log("executor", "retry_with_critique", "info", task=subtask[:60], critique=critique[:60])
        correction_prompt = f"{subtask}\n[CRITIQUE]: {critique}"
        output = self.agent.run(correction_prompt)
        evidence_parts = [
            r.output_snippet
            for r in self.agent.evidence_log._records.values()
            if r.success
        ]
        evidence = " ".join(evidence_parts)
        if not evidence:
            evidence = str(output)
        return str(output), evidence
