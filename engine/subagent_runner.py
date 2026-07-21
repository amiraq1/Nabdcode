"""Subagent runner — isolated execution for the task tool.

Wraps a sub-``ExecutionLoop`` in a separate thread (with a timeout) so a
runaway sub-agent cannot block the parent agent's dispatcher thread. The
sub-loop uses its OWN ``RuntimeState`` and ``EvidenceLog`` passed in by the
caller, guaranteeing the parent's context/evidence is never polluted.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from core.evidence import EvidenceLog
from core.kernel.state import RuntimeState, GoalSpec
from engine.loop import ExecutionLoop


class SubagentRunner:
    """Runs a sub-agent loop in isolation, returning structured results."""

    def __init__(
        self,
        router: Any,
        max_rounds: int = 5,
        timeout: int = 60,
    ) -> None:
        # ``router`` here is the cheap-model ``llm_provider`` callable built by
        # TaskTool (ExecutionLoop expects ``llm_provider``, not a ProviderRouter).
        self._provider = router
        self._max_rounds = max_rounds
        self._timeout = timeout

    def run(self, prompt: str, model: Optional[str] = None) -> dict:
        """Run a sub-agent for ``prompt`` and return a structured dict.

        Returns one of:
          * {"result", "files_read", "tool_calls", "evidence"} on success
          * {"error", "result": ""} on exception or timeout
        """
        sub_state = RuntimeState(
            session_id=f"subagent-{abs(hash(prompt)) % 10**8}",
            active_goal=GoalSpec(raw_prompt=prompt),
        )
        sub_evidence = EvidenceLog()

        loop = ExecutionLoop(
            state=sub_state,
            llm_provider=self._provider,
            evidence_log=sub_evidence,
            no_stream=True,
        )

        result_container: list[dict] = []

        def target() -> None:
            try:
                loop.run(prompt)
                records = sub_evidence.get_records()
                result_container.append(
                    {
                        "result": getattr(loop, "_last_response", "") or "",
                        "evidence": [getattr(r, "evidence_id", "") for r in records],
                        "files_read": [
                            getattr(r, "command_or_path", "")
                            for r in records
                            if getattr(r, "tool", "") in ("file_system", "shell", "code_intelligence")
                            and getattr(r, "command_or_path", "")
                        ],
                        # Each evidence record ~= one tool interaction; capped by
                        # the loop's own budget + the runner timeout below.
                        "tool_calls": min(len(records), self._max_rounds * 3),
                    }
                )
            except Exception as exc:  # never leak into the parent
                result_container.append({"error": str(exc), "result": ""})

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout=self._timeout)
        if t.is_alive():
            return {"error": "Subagent timeout", "result": ""}
        return result_container[0] if result_container else {"error": "No result", "result": ""}
