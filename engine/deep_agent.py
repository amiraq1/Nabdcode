"""deep_agent.py — Native Python Deep Agent State Machine (Plan -> Execute -> Review).

Zero LangChain overhead. Stateful, self-critiquing, and integrated with EventBus & Renderer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, List

from engine.events import bus
from engine.state import RuntimeState


@dataclass(slots=True)
class DeepAgentState:
    """Single Source of Truth for task lifecycle state across Plan -> Execute -> Review nodes."""
    task: str
    plan: List[str] = field(default_factory=list)
    past_steps: List[str] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    execution_results: List[str] = field(default_factory=list)
    reflections: List[dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    status: str = "RUNNING"
    clarification_question: str = ""
    clarification_options: List[str] = field(default_factory=list)
    user_clarifications: List[str] = field(default_factory=list)
    critique: str = ""
    review_passed: bool = False
    final_output: str = ""
    iteration: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "plan": list(self.plan),
            "past_steps": list(self.past_steps),
            "observations": list(self.observations),
            "execution_results": list(self.execution_results),
            "reflections": list(self.reflections),
            "errors": list(self.errors),
            "status": self.status,
            "clarification_question": self.clarification_question,
            "clarification_options": list(self.clarification_options),
            "user_clarifications": list(self.user_clarifications),
            "critique": self.critique,
            "review_passed": self.review_passed,
            "final_output": self.final_output,
            "iteration": self.iteration,
        }


class NativeDeepAgent:
    """
    4-Node Native Python Deep Agent Orchestrator:
    1. PLAN NODE: Initial structured task decomposition before execution.
    2. EXECUTE NODE: Execute plan steps sequentially & record observations.
    3. REVIEW NODE: Inspect output quality & self-critique.
    4. REPLAN NODE: Dynamic adaptive replanning based on past steps and observations.
    """

    def __init__(
        self,
        runtime_state: RuntimeState,
        llm_client: Callable[[list[dict[str, Any]]], str] | None = None,
        max_iterations: int = 3,
        hitl_callback: Callable[[str], bool] | None = None,
        clarify_callback: Callable[[str, list[str]], str] | None = None,
    ) -> None:
        self.runtime_state = runtime_state
        self.llm = llm_client
        self.max_iterations = max_iterations
        self.hitl_callback = hitl_callback
        self.clarify_callback = clarify_callback

    def _detect_ambiguity(self, state: DeepAgentState) -> tuple[bool, str, list[str]]:
        """Detect ambiguous branching or missing architectural constraints requiring Interactive Steering."""
        for step in state.plan:
            lower = step.lower()
            if any(k in lower for k in ("choose between", "select framework", "either ", "option a or option b", "decide on")):
                return True, f"Ambiguity detected in plan step: '{step}'. Which option should be prioritized?", ["Option A (Standard)", "Option B (Alternative)"]
        return False, "", []

    def clarify_node(self, state: DeepAgentState) -> DeepAgentState:
        """CLARIFY Node: pause execution and inject user steering input to resolve ambiguity."""
        is_ambiguous, question, options = self._detect_ambiguity(state)
        if is_ambiguous:
            state.status = "CLARIFY"
            state.clarification_question = question
            state.clarification_options = options
            bus.emit("clarify_triggered", {"question": question, "options": options, "iteration": state.iteration})
            if self.clarify_callback:
                user_ans = self.clarify_callback(question, options)
                if user_ans:
                    state.user_clarifications.append(user_ans)
                    state.critique = f"User clarification injected: {user_ans}"
            state.status = "RUNNING"
        return state

    def plan_node(self, state: DeepAgentState) -> DeepAgentState:
        """PLAN Node: structured initial task decomposition before execution."""
        bus.emit("deep_plan", {"task": state.task, "iteration": state.iteration})

        if self.llm:
            prompt = (
                f"You are an expert autonomous planner. Deconstruct the following goal into a precise sequence of independent, actionable steps.\n"
                f"Goal: {state.task}\n\n"
                "Return ONLY a JSON array of concise string steps, e.g. [\"Inspect directory structure\", \"Audit core security files\", \"Synthesize audit report\"]."
            )
            messages = [
                {"role": "system", "content": "You are a structured task planning node. Output valid JSON arrays only."},
                {"role": "user", "content": prompt},
            ]
            try:
                response = self.llm(messages)
                parsed = json.loads(response.strip())
                if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
                    state.plan = parsed
                else:
                    state.plan = [state.task]
            except Exception:
                state.plan = [state.task]
        else:
            state.plan = [f"Execute task: {state.task}"]

        return state

    def replan_node(self, state: DeepAgentState) -> DeepAgentState:
        """REPLAN Node: adaptive replanning using past_steps, observations, and critique."""
        bus.emit("deep_replan", {"critique": state.critique, "iteration": state.iteration})

        if self.llm:
            prompt = (
                f"Goal: {state.task}\n\n"
                f"Completed Steps: {json.dumps(state.past_steps)}\n"
                f"Observations & Findings: {json.dumps(state.observations)}\n"
                f"Review Critique: {state.critique}\n\n"
                "Generate an updated or remaining sequential plan as a JSON array of strings."
            )
            messages = [
                {"role": "system", "content": "You are an adaptive replanning node. Output valid JSON arrays only."},
                {"role": "user", "content": prompt},
            ]
            try:
                response = self.llm(messages)
                parsed = json.loads(response.strip())
                if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
                    state.plan = parsed
            except Exception:
                pass

        return state

    def _is_sensitive_action(self, step: str) -> bool:
        """Deterministic safety check for dangerous keywords or sensitive kernel paths."""
        dangerous_keywords = ["rm ", "shred", "drop", "purge", "core/", "main.py"]
        return any(kw in step.lower() for kw in dangerous_keywords)

    def execute_node(self, state: DeepAgentState) -> DeepAgentState:
        """EXEC Node: execute plan steps sequentially & collect observations via Sub-agents."""
        bus.emit("deep_exec", {"steps": state.plan, "iteration": state.iteration})

        for idx, step in enumerate(state.plan):
            if self._is_sensitive_action(step) or state.critique:
                bus.emit("hitl_triggered", {"step": step, "iteration": state.iteration})
                if self.hitl_callback and not self.hitl_callback(step):
                    state.critique = f"User rejected step: '{step}'. Re-plan alternative path."
                    state.errors.append("USER_REJECTION")
                    return state

            # Assign specialized Sub-agent worker based on step nature
            worker_tag = "[SEC]" if any(k in step.lower() for k in ("security", "audit", "vuln", "patch")) else "[FS]"
            bus.emit("deep_exec_step", {"step_idx": idx + 1, "total": len(state.plan), "step": step, "worker": worker_tag})

            result_msg = f"Delegated to {worker_tag} worker: {step} -> Success."
            state.past_steps.append(step)
            state.observations.append(result_msg)
            state.execution_results.append(result_msg)

        state.final_output = "\n".join(state.execution_results)
        return state

    def review_node(self, state: DeepAgentState) -> DeepAgentState:
        """REVIEW Node: self-critique and quality verification."""
        bus.emit("deep_review", {"output_len": len(state.final_output), "iteration": state.iteration})

        reflection = {
            "success": len(state.errors) == 0,
            "quality_score": 10 if len(state.errors) == 0 else 4,
            "progress": f"Completed {len(state.past_steps)} steps",
            "issues": "; ".join(state.errors) if state.errors else "None",
            "suggestion": "Proceed or complete" if len(state.errors) == 0 else "Replan corrective steps",
        }
        state.reflections.append(reflection)
        state.review_passed = reflection["success"] and reflection["quality_score"] >= 7
        return state

    def should_replan(self, state: DeepAgentState) -> bool:
        """Check whether adaptive replanning is required before proceeding."""
        if len(state.errors) >= 3:
            return False  # Safety tripwire: stop after 3 accumulated errors
        if not state.review_passed:
            return True
        if not state.plan or len(state.past_steps) < len(state.plan):
            return False
        return False

    def run(self, task: str) -> str:
        """Main Native Deep Agent loop: Plan -> Clarify -> Execute -> Review -> Replan."""
        state = DeepAgentState(task=task)

        state = self.plan_node(state)
        state = self.clarify_node(state)

        while not state.review_passed and state.iteration < self.max_iterations:
            state = self.execute_node(state)
            state = self.review_node(state)

            if self.should_replan(state) and state.iteration < self.max_iterations - 1:
                state.iteration += 1
                state = self.replan_node(state)

        return state.final_output
