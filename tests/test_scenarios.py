"""Phase 5 — End-to-End Scenarios, Self-Healing Watchdog & Parallel Shared Memory Tests."""

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.monitoring import EventLogger
from core.state_manager import SharedStateManager
from multi_agent.executor import ExecutorAgent
from multi_agent.orchestrator import Orchestrator
from multi_agent.planner import PlannerAgent
from multi_agent.verifier import VerifierAgent


class MockExecutor:
    def __init__(self, mem: str = "") -> None:
        self.mem = mem

    def run_single(self, subtask: str) -> tuple[str, str]:
        if "ghost" in subtask or "غير موجود" in subtask:
            return "File not found", "error reading ghost.py"
        if "sanitize.py" in subtask:
            return "Analyzed sanitize", "Found _PATTERN = re.compile in core/sanitize.py"
        if "memory.py" in subtask:
            return "Analyzed memory", "Found load_memory in core/memory.py"
        return "Done", f"Evidence `re.compile` for {subtask}"

    def retry_with_critique(self, subtask: str, critique: str) -> tuple[str, str]:
        return "Retried Done", f"Quoted evidence `re.compile` for {subtask}"


class TestScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.state_file = Path("core/state/test_scenarios_state.json")
        self.log_file = Path("core/state/agent_log.jsonl")

    def test_e2e_count_regex(self) -> None:
        """Scenario 1: End-to-End integration verifying regex pattern counting and quoting."""
        goal = "Read core/sanitize.py and count compiled regex patterns"
        planner = PlannerAgent(
            llm_fn=lambda msgs: """[
              {"id": "1", "goal": "Read core/sanitize.py", "depends_on": []},
              {"id": "2", "goal": "Count _PATTERN = re.compile", "depends_on": ["1"]}
            ]"""
        )
        verifier = VerifierAgent(llm_fn=lambda msgs: "Verdict: PASS")
        orch = Orchestrator(
            planner=planner,
            executor_factory=lambda mem: MockExecutor(mem),
            verifier=verifier,
        )

        result = orch.run_parallel(goal)
        self.assertIn("re.compile", result)
        self.assertTrue(
            "evidence" in result.lower() or "`" in result or "core/sanitize.py" in result
        )

    def test_supervisor_replan(self) -> None:
        """Scenario 2: Supervisor watchdog self-healing intervention on repeated failures."""
        goal = "اقرأ ملف غير موجود core/ghost.py ثم عد الأسطر"
        # Simulate 3 previous failure events in agent_log for task id 1
        EventLogger.log("verifier:100", "verify", "FAIL")
        EventLogger.log("verifier:100", "verify", "FAIL")
        EventLogger.log("verifier:100", "verify", "FAIL")

        planner = PlannerAgent(
            llm_fn=lambda msgs: "Read existing file core/sanitize.py and extract lines"
        )
        orch = Orchestrator(planner=planner, max_budget_seconds=180)
        state_mgr = SharedStateManager(state_path=self.state_file)

        tasks = [{"id": "100", "goal": goal, "depends_on": []}]
        replanned_tasks = orch.supervisor_watchdog(tasks, state_mgr)

        self.assertTrue(replanned_tasks[0].get("retry_by_supervisor"))
        self.assertNotEqual(replanned_tasks[0]["goal"], goal)

        if self.log_file.exists():
            logs = self.log_file.read_text(encoding="utf-8")
            self.assertTrue("intervention" in logs or "replan" in logs)

    def test_parallel_shared_memory(self) -> None:
        """Scenario 3: Parallel execution storing combined findings in shared memory."""
        goal = "حلل core/sanitize.py و core/memory.py بالتوازي"
        planner = PlannerAgent(
            llm_fn=lambda msgs: """[
              {"id": "1", "goal": "Analyze core/sanitize.py", "depends_on": []},
              {"id": "2", "goal": "Analyze core/memory.py", "depends_on": []}
            ]"""
        )
        verifier = VerifierAgent(llm_fn=lambda msgs: "Verdict: PASS")
        orch = Orchestrator(
            planner=planner,
            executor_factory=lambda mem: MockExecutor(mem),
            verifier=verifier,
        )

        start = time.time()
        result = orch.run_parallel(goal)
        elapsed = time.time() - start

        self.assertIn("sanitize.py", result)
        self.assertIn("memory.py", result)
        self.assertLess(elapsed, 40)


if __name__ == "__main__":
    unittest.main()
