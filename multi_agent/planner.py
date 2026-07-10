from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from llm_router import execute_agent_with_memory


class PlannerAgent:
    """Planner agent responsible for breaking down a goal into verifiable subtasks."""

    def __init__(self, llm_fn: Callable[[list[dict[str, Any]]], str] | None = None):
        self.llm_fn = llm_fn or execute_agent_with_memory

    def plan(self, goal: str) -> list[str]:
        agent_md = Path("AGENT.md")
        rules = agent_md.read_text(encoding="utf-8")[:1000] if agent_md.exists() else ""
        prompt = f"""You are the Planner. Break the goal into 1-3 single, verifiable subtasks.
Rules from AGENT.md: {rules}

Goal: {goal}

Return as JSON list: ["task1", "task2"]
Example: "Read sanitize.py and count regex" -> ["Read core/sanitize.py", "Count compiled regex _PATTERN = re.compile"]
"""
        raw = self.llm_fn([{"role": "user", "content": prompt}])
        return self._parse_json_list(raw, goal)

    def plan_with_deps(self, goal: str) -> list[dict[str, Any]]:
        """Plan subtasks with explicit dependency graph for parallel execution."""
        agent_md = Path("AGENT.md")
        rules = agent_md.read_text(encoding="utf-8")[:1000] if agent_md.exists() else ""
        prompt = f"""You are the Planner. Break the goal into 1-4 verifiable subtasks with dependency graph.
Rules from AGENT.md: {rules}

Goal: {goal}

Return JSON list of objects:
[
  {{"id": "1", "goal": "Read core/sanitize.py", "depends_on": []}},
  {{"id": "2", "goal": "Read core/memory.py", "depends_on": []}},
  {{"id": "3", "goal": "Compare patterns between sanitize and memory", "depends_on": ["1", "2"]}}
]"""
        raw = self.llm_fn([{"role": "user", "content": prompt}])
        try:
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw[start : end + 1])
                if (
                    isinstance(data, list)
                    and len(data) > 0
                    and all(
                        isinstance(item, dict) and "id" in item and "goal" in item
                        for item in data
                    )
                ):
                    for idx, item in enumerate(data):
                        item["id"] = str(item["id"])
                        item.setdefault("depends_on", [])
                        item["status"] = "pending"
                    return data
        except Exception:
            pass
        # Fallback: plan simple subtasks and convert to dependency structure
        subtasks = self.plan(goal)
        result = []
        for idx, st in enumerate(subtasks):
            result.append(
                {
                    "id": str(idx + 1),
                    "goal": st,
                    "depends_on": [] if idx == 0 else [str(idx)],
                    "status": "pending",
                }
            )
        return result

    def _parse_json_list(self, raw: str, goal: str) -> list[str]:
        if not raw or not raw.strip():
            return [goal]
        try:
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw[start : end + 1])
                if (
                    isinstance(data, list)
                    and all(isinstance(item, str) for item in data)
                    and len(data) > 0
                ):
                    return [item.strip() for item in data if item.strip()]
        except Exception:
            pass
        lines = [line.strip("- *").strip() for line in raw.splitlines() if line.strip()]
        valid = [l for l in lines if len(l) > 3 and not l.startswith("```")]
        return valid if valid else [goal]

    def replan(self, prompt: str) -> str:
        """Replan a failed task into a simpler, single verifiable subtask."""
        raw = self.llm_fn([{"role": "user", "content": prompt}])
        if not raw or not raw.strip():
            return "Read file and quote exact snippet"
        lines = [l.strip("- *").strip() for l in raw.splitlines() if l.strip()]
        for l in lines:
            if len(l) > 3 and not l.startswith("```"):
                return l
        return raw.strip()
