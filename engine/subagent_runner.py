"""Subagent runner — bounded, read-only delegation for the ``task`` tool.

Delegated tasks are intended for research, exploration, and verification.  They
therefore receive their own runtime state and evidence log *and* a filtered tool
registry.  The child cannot modify project files, execute shell commands, or
spawn another child loop through the normal tool path.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from core.evidence import EvidenceLog
from core.kernel.state import RuntimeState, GoalSpec
from engine.dispatcher import Dispatcher
from engine.loop import ExecutionLoop
from engine.subagent_policy import RestrictedToolRegistry
from engine.tool_registry import registry


class SubagentRunner:
    """Run a bounded, read-only sub-agent loop and return a structured result."""

    def __init__(
        self,
        router: Any,
        max_rounds: int = 5,
        timeout: int = 60,
        tool_registry: Any = None,
    ) -> None:
        # ``router`` here is the cheap-model ``llm_provider`` callable built by
        # TaskTool (ExecutionLoop expects ``llm_provider``, not a ProviderRouter).
        self._provider = router
        self._max_rounds = max(1, int(max_rounds))
        self._timeout = max(1, int(timeout))
        self._source_registry = tool_registry or registry

    def run(self, prompt: str, model: Optional[str] = None) -> dict:
        """Run a delegated task with isolated state, evidence, budget, and tools.

        Returns one of:
          * ``{"result", "files_read", "tool_calls", "evidence"}`` on success;
          * ``{"error", "result": ""}`` when the child fails or reaches its wall-clock timeout.
        """
        sub_state = RuntimeState(
            session_id=f"subagent-{abs(hash(prompt)) % 10**8}",
            active_goal=GoalSpec(raw_prompt=prompt),
            # ``max_rounds`` was previously only used to cap a reported count.
            # Bind it to RuntimeState so it limits the child execution loop.
            max_steps=self._max_rounds,
        )
        sub_evidence = EvidenceLog()
        restricted_registry = RestrictedToolRegistry(self._source_registry)
        restricted_dispatcher = Dispatcher(sub_state, tool_registry=restricted_registry)

        loop = ExecutionLoop(
            state=sub_state,
            llm_provider=self._provider,
            evidence_log=sub_evidence,
            dispatcher=restricted_dispatcher,
            tool_registry=restricted_registry,
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
                            if getattr(r, "tool", "") in ("file_system", "code_intelligence")
                            and getattr(r, "command_or_path", "")
                        ],
                        # Each evidence record ~= one tool interaction; cap the
                        # reported count at the real child step budget.
                        "tool_calls": min(len(records), self._max_rounds),
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
