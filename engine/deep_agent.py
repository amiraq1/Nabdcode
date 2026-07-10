"""deep_agent.py — Native Python Deep Agent State Machine (Plan -> Execute -> Review).

Zero LangChain overhead. Stateful, self-critiquing, and integrated with EventBus & Renderer.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List

from engine.events import bus
from engine.state import RuntimeState
from engine.dispatcher import Dispatcher
from core.parser import extract_command
from core.evidence import EvidenceLog, VerifierError
from tools.models import ToolResult
from core.sanitize import sanitize


def extract_json_array(raw_output: str) -> List[Any]:
    """Robust JSON Array extractor resilient against Llama-3/70B thinking blocks and markdown fences."""
    if not raw_output or not isinstance(raw_output, str):
        return []

    text = sanitize(raw_output).strip()
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text)

    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        candidate = match.group(0)
        try:
            parsed = json.loads(sanitize(candidate))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(sanitize(text))
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    return []


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
        dispatcher: Dispatcher | None = None,
        evidence_log: EvidenceLog | None = None,
    ) -> None:
        self.runtime_state = runtime_state
        self.llm = llm_client
        self.max_iterations = max_iterations
        self.hitl_callback = hitl_callback
        self.clarify_callback = clarify_callback
        self.dispatcher = dispatcher or Dispatcher(runtime_state)
        self.evidence_log = evidence_log or EvidenceLog()

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
                "Return ONLY a valid JSON array of strings. No thinking, no explanation, no markdown."
            )
            messages = [
                {"role": "system", "content": "You are a structured task planning node. Output valid JSON arrays only. No markdown or preamble."},
                {"role": "user", "content": prompt},
            ]
            for attempt in range(1, 4):
                try:
                    response = self.llm(messages)
                    parsed = extract_json_array(response)
                    if parsed and all(isinstance(s, str) for s in parsed):
                        sys.stdout.write("\r\033[K")
                        sys.stdout.flush()
                        state.plan = [s.strip() for s in parsed if s.strip()]
                        return state
                except Exception:
                    time.sleep(0.4)
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
                "Return ONLY a valid JSON array of remaining string steps. No thinking, no explanation, no markdown."
            )
            messages = [
                {"role": "system", "content": "You are an adaptive replanning node. Output valid JSON arrays only. No markdown or preamble."},
                {"role": "user", "content": prompt},
            ]
            for attempt in range(1, 4):
                try:
                    response = self.llm(messages)
                    parsed = extract_json_array(response)
                    if parsed and all(isinstance(s, str) for s in parsed):
                        sys.stdout.write("\r\033[K")
                        sys.stdout.flush()
                        state.plan = [s.strip() for s in parsed if s.strip()]
                        return state
                except Exception:
                    time.sleep(0.4)

        return state

    def _is_sensitive_action(self, step: str) -> bool:
        """Deterministic safety check for dangerous keywords or sensitive kernel paths."""
        dangerous_keywords = ["rm ", "shred", "drop", "purge", "core/", "main.py"]
        return any(kw in step.lower() for kw in dangerous_keywords)

    def execute_node(self, state: DeepAgentState) -> DeepAgentState:
        """EXEC Node: execute plan steps sequentially via LLM -> tool dispatch -> observation."""
        bus.emit("deep_exec", {"steps": state.plan, "iteration": state.iteration})

        if not self.llm:
            state.errors.append("NO_LLM")
            return state

        for idx, step in enumerate(state.plan):
            if self._is_sensitive_action(step) or state.critique:
                bus.emit("hitl_triggered", {"step": step, "iteration": state.iteration})
                if self.hitl_callback and not self.hitl_callback(step):
                    state.critique = f"User rejected step: '{step}'. Re-plan alternative path."
                    state.errors.append("USER_REJECTION")
                    return state

            worker_tag = "[SEC]" if any(k in step.lower() for k in ("security", "audit", "vuln", "patch")) else "[FS]"
            bus.emit("deep_exec_step", {"step_idx": idx + 1, "total": len(state.plan), "step": step, "worker": worker_tag})

            # Build context from this plan step, past observations, and tool schemas
            tool_schemas = self._tool_schemas_summary()
            exec_prompt = (
                f"You are executing plan step {idx+1}/{len(state.plan)} for the goal: {state.task}\n"
                f"Current step: {step}\n\n"
                f"Available tools: {tool_schemas}\n\n"
                f"Use exactly ONE tool to accomplish this step. "
                f"Return ONLY a valid JSON tool call wrapped in ```json ... ```. No explanation."
            )
            messages = [
                {"role": "system", "content": "You are a precise tool-calling agent. Output one JSON tool call per step."},
                {"role": "user", "content": exec_prompt},
            ]

            result = None
            for attempt in range(3):
                try:
                    response = self.llm(messages)
                except Exception as exc:
                    state.errors.append(f"LLM_ERROR: {exc}")
                    continue

                tool_call = extract_command(response)
                if tool_call is None:
                    state.errors.append(f"PARSE_FAILURE: LLM did not produce a tool call for step '{step[:60]}'")
                    continue

                try:
                    result = self.dispatcher.dispatch(tool_call.tool, tool_call.args)
                    if result is None:
                        result = ToolResult(success=False, stderr="Dispatcher returned None", returncode=-1)
                    # Record evidence for every dispatched tool call (success or failure)
                    cmd_summary = (
                        tool_call.args.get("command")
                        or tool_call.args.get("path")
                        or tool_call.args.get("query")
                        or str(tool_call.args)[:60]
                    )
                    self.evidence_log.record(
                        tool=tool_call.tool,
                        command_or_path=cmd_summary,
                        success=getattr(result, "success", False),
                        output_snippet=getattr(result, "output", "") or getattr(result, "stderr", ""),
                    )
                    break
                except Exception as exc:
                    state.errors.append(f"DISPATCH_ERROR: {exc}")
                    continue

            if result is None:
                err_msg = f"Step '{step[:80]}' failed after 3 attempts."
                state.past_steps.append(step)
                state.observations.append(f"[ERROR] {err_msg}")
                state.execution_results.append(f"[Execution Error] {err_msg}")
                continue

            # Record real observation
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            snippet = output[:500] + ("..." if len(output) > 500 else "")
            observation = (
                f"[OK] {step[:80]}\n"
                f"  tool: {tool_call.tool}\n"
                f"  exit: {result.returncode}\n"
                f"  output: {snippet}"
            ) if result.success else (
                f"[FAIL] {step[:80]}\n"
                f"  tool: {tool_call.tool}\n"
                f"  exit: {result.returncode}\n"
                f"  error: {snippet}"
            )
            state.past_steps.append(step)
            state.observations.append(observation)
            state.execution_results.append(
                output if result.success else f"[Error] {output or 'No output'}"
            )

        state.final_output = "\n".join(state.execution_results)
        return state

    def _tool_schemas_summary(self) -> str:
        """Return a compact summary of available tools for the execute prompt."""
        from engine.tool_registry import registry
        schemas = registry.get_all_schemas()
        return "; ".join(
            f"{s['name']}: {s.get('description', '')[:80]}"
            for s in schemas
        )

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
        """Main Native Deep Agent loop: Plan -> Clarify -> Execute -> Review -> Replan.

        After the review loop passes, runs EvidenceLog.verify() as a final
        gate before returning the output — same as ExecutionLoop's no-tool-call
        path.  If verification fails, raises VerifierError (propagated as
        ToolRequiredError by the caller).

        DESIGN DECISION — TodoManager ownership:
          NativeDeepAgent manages its own plan via DeepAgentState.plan and does
          NOT write to the shared TodoManager.  Two parallel task lists (one on
          screen, one internal) would cause confusion.  The ExecutionLoop path
          owns TodoManager; the deep agent path owns DeepAgentState.plan.
        """
        state = DeepAgentState(task=task)

        state = self.plan_node(state)
        state = self.clarify_node(state)

        while not state.review_passed and state.iteration < self.max_iterations:
            state = self.execute_node(state)
            state = self.review_node(state)

            if self.should_replan(state) and state.iteration < self.max_iterations - 1:
                state.iteration += 1
                state = self.replan_node(state)

        # Check chitchat first
        from core.constants import is_chitchat
        is_chat, _ = is_chitchat(task)
        if is_chat and not state.past_steps:
            return state.final_output

        # Final evidence verification gate with self-correction
        retry_count = 0
        MAX_SELF_CORRECT = 3
        while retry_count <= MAX_SELF_CORRECT:
            try:
                self.evidence_log.verify(require_tools=True, claim=state.final_output)
                return state.final_output
            except Exception as verr:
                if retry_count == MAX_SELF_CORRECT:
                    state.final_output = (
                        f"تعذر إكمال المهمة بعد {MAX_SELF_CORRECT} محاولات تصحيح ذاتي. آخر خطأ: {verr}"
                    )
                    break
                critique = (
                    f"[VERIFIER CRITIQUE]: {verr}. صحح مسارك وأعد المحاولة بالأداة الصحيحة."
                )
                state.observations.append(critique)
                state.iteration += 1
                state = self.execute_node(state)
                state = self.review_node(state)
                retry_count += 1

        return state.final_output


def classify_intent(text: str) -> str:
    """Classify user intent to prevent overthinking simple queries."""
    text_lower = text.lower().strip()
    if text_lower in {"hi", "hello", "hey", "iraq", "مرحبا", "هلا"}:
        return "direct_response"
    if re.search(r'^\s*\d+\s*[\+\-\*\/]\s*\d+', text):
        return "use_calculator"
    if any(w in text_lower for w in ("count", "read", "grep", "file", "list")):
        return "use_tools"
    return "default"

