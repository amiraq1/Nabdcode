from __future__ import annotations

import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from core.memory import load_memory, write_lesson
from core.monitoring import EventLogger
from core.state_manager import SharedStateManager
from multi_agent.planner import PlannerAgent
from multi_agent.executor import ExecutorAgent
from multi_agent.verifier import VerifierAgent


class Orchestrator:
    """Orchestrates multi-agent sequential and parallel execution with supervisor watchdog."""

    def __init__(
        self,
        planner: PlannerAgent | None = None,
        executor_factory: Callable[[str], Any] | None = None,
        verifier: VerifierAgent | None = None,
        max_budget_seconds: int = 180,
    ):
        self.planner = planner or PlannerAgent()
        self.executor_factory = executor_factory or (lambda mem: ExecutorAgent(memory=mem))
        self.verifier = verifier or VerifierAgent()
        self.max_budget_seconds = max_budget_seconds

    def run(self, goal: str) -> str:
        start = time.time()
        subtasks = self.planner.plan(goal)

        all_evidence: list[str] = []
        for i, subtask in enumerate(subtasks):
            if time.time() - start > self.max_budget_seconds:
                return f"Budget Ceiling after {i} tasks"

            executor = self.executor_factory(load_memory())
            output, evidence = executor.run_single(subtask)

            if not self.verifier.verify_fresh(output, evidence):
                output, evidence = executor.retry_with_critique(
                    subtask, "اقتبس الدليل حرفيا"
                )

            all_evidence.append(evidence)
            write_lesson(f"Subtask {subtask}", f"Solved via {evidence[:100]}")

        return self._synthesize(goal, all_evidence)

    def supervisor_watchdog(
        self, tasks: list[dict[str, Any]], state_mgr: SharedStateManager
    ) -> list[dict[str, Any]]:
        """Watchdog inspecting log for repeated failures (>=3) and replanning simpler subtasks."""
        LOG_FILE = Path("core/state/agent_log.jsonl")
        if not LOG_FILE.exists():
            return tasks

        fails = Counter()
        for line in LOG_FILE.read_text(encoding="utf-8").splitlines()[-30:]:
            try:
                e = json.loads(line)
                if e.get("status") == "FAIL":
                    tid = str(e.get("agent", "")).split(":")[-1]
                    fails[tid] += 1
            except Exception:
                continue

        new_tasks = []
        for t in tasks:
            tid = str(t.get("id", ""))
            if fails[tid] >= 3:
                EventLogger.log("supervisor", "intervention", "warn", task_id=tid, fails=fails[tid])
                shared_ctx = state_mgr.get_shared_context()
                replan_prompt = f"""Task {tid} failed 3 times: {t['goal']}
Shared evidence so far: {shared_ctx}
Replan it into a simpler, more verifiable subtask.
Return ONE task only."""
                simpler_task = self.planner.replan(replan_prompt)
                t["goal"] = simpler_task
                t["retry_by_supervisor"] = True
                EventLogger.log("supervisor", "replan", "info", task_id=tid, new_goal=simpler_task[:60])
            new_tasks.append(t)
        return new_tasks

    def _execute_levels(
        self, tasks: list[dict[str, Any]], state_mgr: SharedStateManager
    ) -> None:
        level_0 = [t for t in tasks if not t.get("depends_on")]
        level_1 = [t for t in tasks if t.get("depends_on")]

        def execute_one(task: dict[str, Any]) -> tuple[str, bool]:
            shared_ctx = state_mgr.get_shared_context()
            executor = self.executor_factory(shared_ctx)
            output, evidence = executor.run_single(task["goal"])
            if self.verifier.verify_fresh(output, evidence):
                state_mgr.add_evidence(task["id"], evidence)
                state_mgr.update_task_status(task["id"], "done")
                return task["id"], True
            output, evidence = executor.retry_with_critique(
                task["goal"], "اقتبس الدليل حرفيا"
            )
            state_mgr.add_evidence(task["id"], evidence)
            state_mgr.update_task_status(task["id"], "done")
            return task["id"], True

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(execute_one, t): t for t in level_0}
            for f in as_completed(futures):
                try:
                    tid, ok = f.result()
                    print(f"Task {tid} finished (ok={ok})")
                except Exception as e:
                    print(f"Task exception: {e}")

        for t in level_1:
            execute_one(t)

    def run_parallel(self, goal: str) -> str:
        start = time.time()
        state_mgr = SharedStateManager()
        tasks = self.planner.plan_with_deps(goal)
        state_mgr._write({"goal": goal, "tasks": tasks, "shared_evidence": [], "log": []})

        max_supervisor_rounds = 2
        for r in range(max_supervisor_rounds):
            EventLogger.log("orchestrator", "level_start", "info", level="0", round=r + 1, workers=2)
            EventLogger.log(
                "orchestrator",
                "budget",
                "info",
                elapsed=int(time.time() - start),
                budget=self.max_budget_seconds,
            )

            self._execute_levels(tasks, state_mgr)

            metrics = EventLogger.get_metrics()
            if metrics["fails"] == 0:
                break

            tasks = self.supervisor_watchdog(tasks, state_mgr)
            EventLogger.log("orchestrator", "supervisor_round", "info", round=r + 1)

            if time.time() - start > self.max_budget_seconds:
                return "Budget Ceiling في الإشراف"

        return state_mgr.get_shared_context()

    def _synthesize(self, goal: str, all_evidence: list[str]) -> str:
        combined = "\n".join(f"- {ev}" for ev in all_evidence)
        return f"Completed Goal: {goal}\nEvidence Summary:\n{combined}"


if __name__ == "__main__":
    prompt = "حلل core/sanitize.py و core/memory.py"
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    print(f"Starting parallel orchestration for: {prompt}")
    orch = Orchestrator()
    res = orch.run_parallel(prompt)
    print("\n--- Shared Context Result ---")
    print(res)
