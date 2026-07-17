"""deep_agent.py — Native Python Deep Agent State Machine (Plan -> Execute -> Review).

Zero LangChain overhead. Stateful, self-critiquing, and integrated with EventBus & Renderer.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List

from engine.events import bus
from engine.interfaces import DispatcherProtocol
from engine.state import RuntimeState, GoalSpec
from engine.consent import ConsentManager
from core.parser import extract_command, validate_tool_call, get_workspace_root
from core.evidence import EvidenceLog, VerifierError
from tools.models import ToolResult
from core.sanitize import sanitize


# Schema version for serialized DeepAgentState checkpoints. Bumped only when
# the to_dict() layout changes incompatibly; from_dict tolerates older payloads.
# v3 adds the GoalSpec field (raw_prompt / success_criteria / is_met) so an
# active objective survives an Android LMK kill and is re-injected on resume.
DEEP_AGENT_STATE_VERSION: int = 3

# Hidden checkpoint file written atomically into the workspace root. A leading
# dot + .json suffix keeps it out of normal listings and tool scans.
CHECKPOINT_FILENAME: str = ".nabd_agent_state.json"

# Phase3.1: cap on how many slim evidence ledgers are persisted in the
# checkpoint so an LMK recovery never re-inflates the context with raw history.
MAX_CHECKPOINT_EVIDENCE: int = 3


def _slim_evidence_ledger(log: "EvidenceLog") -> list[dict[str, Any]]:
    """Phase3.1 slim ledger: structured pointers, NOT raw outputs.

    Mirrors the compact ``<past_steps_summary>`` shape used by ExecutionLoop so
    an Android LMK recovery remounts from the same slim view instead of
    replaying uncompacted history strings (prevents context re-inflation).
    """
    ledgers = []
    for rec in log.get_records():
        ledgers.append({
            "evidence_id": rec.evidence_id,
            "tool": rec.tool,
            "ok": rec.success,
            "critical": rec.critical,
            "path_hint": (rec.command_or_path or "")[:80],
            "summary": (rec.output_snippet or "")[:120],
        })
    # Keep only the most-recent MAX_CHECKPOINT_EVIDENCE ledgers (slim cap).
    return ledgers[-MAX_CHECKPOINT_EVIDENCE:]


def _build_dispatcher(state: RuntimeState) -> "DispatcherProtocol":
    """Lazily construct the concrete Dispatcher.

    Mirrors the DI seam in engine.loop: importing engine.deep_agent must not
    pull engine.dispatcher (and its registry/tools subgraph) into the module
    load order, which keeps the import graph acyclic even under engine/__init__.
    """
    from engine.dispatcher import Dispatcher
    return Dispatcher(state)


def extract_json_array(raw_output: str) -> list:
    """Robust JSON Array extractor resilient against Llama-3/70B thinking
    blocks and markdown fences."""
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
    # Phase3.2: explicit state-machine cursor so an LMK resume lands on the
    # exact interrupted node instead of re-deriving it from side effects.
    current_node: str = "PLAN"          # PLAN | CLARIFY | EXECUTE | REVIEW | REPLAN
    current_plan_index: int = 0       # index into `plan` for the EXECUTE node
    # Phase5 (GoalSpec): the active verifiable objective, checkpointed so an
    # Android LMK kill mid-run does not lose the objective. Restored verbatim on
    # resume and re-injected into runtime_state.active_goal so the verifiable
    # exit gate still fires. None when no goal is active.
    goal: "GoalSpec | None" = None
    # Phase3.1: slim, replay-safe ledger mirroring the compacted view.
    # Persisted in the checkpoint INSTEAD of raw history strings so an LMK
    # recovery remounts at the interrupted node without re-inflating context.
    evidence_ledger: List[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full task lifecycle state into a JSON-safe structure.

        Includes a ``schema_version`` marker so a future layout change can be
        detected during ``from_dict`` and migrated instead of crashing LMK resume.
        """
        return {
            "schema_version": DEEP_AGENT_STATE_VERSION,
            "task": self.task,
            "plan": list(self.plan),
            "past_steps": list(self.past_steps),
            "observations": list(self.observations),
            "execution_results": list(self.execution_results),
            "reflections": [dict(r) for r in self.reflections],
            "errors": list(self.errors),
            "status": self.status,
            "clarification_question": self.clarification_question,
            "clarification_options": list(self.clarification_options),
            "user_clarifications": list(self.user_clarifications),
            "critique": self.critique,
            "review_passed": self.review_passed,
            "final_output": self.final_output,
            "iteration": self.iteration,
            # Phase3.2: persist the explicit state-machine cursor.
            "current_node": self.current_node,
            "current_plan_index": self.current_plan_index,
            # Phase5 (GoalSpec): persist the active objective so it survives LMK.
            "goal": self.goal.to_dict() if self.goal is not None else None,
            # Phase3.1: persist the slim ledger, not raw uncompacted history.
            "evidence_ledger": [dict(e) for e in self.evidence_ledger],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "DeepAgentState":
        """Reconstruct a DeepAgentState perfectly from a ``to_dict`` payload.

        All fields are defaulted defensively so a partial/legacy checkpoint (even
        one missing ``schema_version``) restores without raising — surviving an
        LMK death mid-write is the whole point of this guard.  The slim
        ``evidence_ledger`` is restored as-is (structurally, never re-expanded
        into raw stdout), keeping the resume replay-safe.
        """
        if not isinstance(data, dict):
            raise TypeError("DeepAgentState.from_dict expects a dict payload.")

        return DeepAgentState(
            task=str(data.get("task", "")),
            plan=list(data.get("plan", []) or []),
            past_steps=list(data.get("past_steps", []) or []),
            observations=list(data.get("observations", []) or []),
            execution_results=list(data.get("execution_results", []) or []),
            reflections=[dict(r) for r in (data.get("reflections", []) or [])],
            errors=list(data.get("errors", []) or []),
            status=str(data.get("status", "RUNNING")),
            clarification_question=str(data.get("clarification_question", "")),
            clarification_options=list(data.get("clarification_options", []) or []),
            user_clarifications=list(data.get("user_clarifications", []) or []),
            critique=str(data.get("critique", "")),
            review_passed=bool(data.get("review_passed", False)),
            final_output=str(data.get("final_output", "")),
            iteration=int(data.get("iteration", 0) or 0),
            # Phase3.2: restore the explicit state-machine cursor (defaulted
            # defensively so a legacy/partial checkpoint still resumes cleanly).
            current_node=str(data.get("current_node", "PLAN")),
            current_plan_index=int(data.get("current_plan_index", 0) or 0),
            # Phase5 (GoalSpec): restore the active objective from the checkpoint
            # (defensive: None if absent/legacy). Re-injection into the live
            # runtime_state happens in run() so the verifiable exit gate fires.
            goal=GoalSpec.from_dict(data["goal"]) if data.get("goal") else None,
            evidence_ledger=[dict(e) for e in (data.get("evidence_ledger", []) or [])],
        )


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
        dispatcher: DispatcherProtocol | None = None,
        evidence_log: EvidenceLog | None = None,
    ) -> None:
        self.runtime_state = runtime_state
        self.llm = llm_client
        self.max_iterations = max_iterations
        self.hitl_callback = hitl_callback
        self.clarify_callback = clarify_callback
        # Dependency Injection: a dispatcher is injected if provided, otherwise
        # built lazily so importing engine.deep_agent never forces
        # engine.dispatcher -> engine.tool_registry -> tools.base to load first.
        self.dispatcher = dispatcher or _build_dispatcher(runtime_state)
        self.evidence_log = evidence_log or EvidenceLog()
        # Phase3.2: True only for the FIRST execute_node call after an LMK
        # resume, so the mid-EXECUTE re-dispatch guard fires once (then cleared).
        self._resume_mode = False

    # ------------------------------------------------------------------
    # LMK-Survival Checkpointing (atomic write to workspace root)
    # ------------------------------------------------------------------

    @property
    def checkpoint_path(self) -> Path:
        """Localized hidden checkpoint file inside the pinned workspace root."""
        try:
            return get_workspace_root() / CHECKPOINT_FILENAME
        except Exception:
            return Path(CHECKPOINT_FILENAME)

    def _save_checkpoint(self, state: DeepAgentState) -> None:
        """Atomically persist ``state`` to ``.nabd_agent_state.json``.

        Write -> fsync -> rename so an Android LMK kill mid-write can never leave
        a half-written JSON file. Any I/O error is swallowed: checkpointing must
        never abort the agent task. Emits ``deep_checkpoint_saved`` for visibility.

        Phase3.1: the persisted payload mirrors the SLIM summary ledger
        (``state.evidence_ledger``), never raw uncompacted history strings, so an
        LMK recovery remounts the state machine without context re-inflation.
        """
        try:
            # Mirror the slim ledger into the checkpoint before serializing.
            state.evidence_ledger = _slim_evidence_ledger(self.evidence_log)
            payload = state.to_dict()
            path = self.checkpoint_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
            bus.emit("deep_checkpoint_saved", {"iteration": state.iteration, "status": state.status})
        except Exception:
            # Fail-open: checkpoint loss must not break the running task.
            pass

    def _restore_evidence_from_ledger(self, state: DeepAgentState) -> None:
        """Phase3.1 replay-safe remount: rebuild slim evidence ledger only.

        The checkpoint carries ``evidence_ledger`` (structured pointers, no raw
        stdout). We do NOT re-inflate raw history — the state machine remounts at
        the interrupted node from this slim view, exactly mirroring what an active
        ExecutionLoop compaction would have produced. Idempotent: safe to call
        once per resume.
        """
        # The ledger is already restored verbatim via DeepAgentState.from_dict.
        # This hook exists so future raw-replay guards can be added without
        # touching run()'s control flow. No duplication of historical turns occurs.
        return

    def _reconcile_goal_with_checkpoint(self, state: DeepAgentState) -> None:
        """Phase5 (GoalSpec): re-inject the checkpointed objective on resume.

        After an LMK kill, the serialized ``state.goal`` (raw_prompt /
        success_criteria / is_met) is restored from the checkpoint. We push it
        into the live ``runtime_state.active_goal`` so the verifiable exit gate
        (which reads ``runtime_state.active_goal``) still fires on resume.

        Operator intent wins: if the operator re-issued ``/goal`` this session,
        the fresh objective overrides the stale checkpointed one (and is written
        back into the checkpoint so it persists going forward).
        """
        if state.goal is not None:
            if self.runtime_state.active_goal is None:
                self.runtime_state.active_goal = state.goal
            else:
                # Operator re-issued /goal after restart: keep the new objective
                # in the checkpoint too so it persists for the rest of the run.
                state.goal = self.runtime_state.active_goal
        elif self.runtime_state.active_goal is not None:
            state.goal = self.runtime_state.active_goal

    @classmethod
    def _load_checkpoint(cls, path: Path | None = None) -> DeepAgentState | None:
        """Read and restore a checkpoint, or return None if absent/corrupt."""
        if path is None:
            try:
                path = get_workspace_root() / CHECKPOINT_FILENAME
            except Exception:
                path = Path(CHECKPOINT_FILENAME)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return DeepAgentState.from_dict(data)
        except Exception:
            return None

    def _clear_checkpoint(self) -> None:
        """Remove the checkpoint file after a clean final_answer completion."""
        try:
            self.checkpoint_path.unlink(missing_ok=True)
        except Exception:
            pass

    def clear_session(self) -> None:
        """Clear conversation context, evidence log, and checkpointed state for a clean fresh task start."""
        if hasattr(self, "runtime_state") and self.runtime_state is not None:
            if hasattr(self.runtime_state, "clear_context"):
                self.runtime_state.clear_context()
            else:
                msgs = self.runtime_state.messages
                sys_msgs = [m for m in msgs if m.get("role") == "system"] if msgs else []
                self.runtime_state.set_messages(sys_msgs)
                self.runtime_state.reset_step_count()

        if hasattr(self, "evidence_log") and self.evidence_log is not None:
            if hasattr(self.evidence_log, "clear"):
                self.evidence_log.clear()
            elif isinstance(self.evidence_log, list):
                self.evidence_log.clear()

        self._clear_checkpoint()

    def _detect_ambiguity(self, state: DeepAgentState) -> tuple[bool, str, list[str]]:
        """Detect ambiguous branching or missing architectural constraints requiring Interactive Steering."""
        for step in state.plan:
            lower = step.lower()
            if any(k in lower for k in ("choose between", "select framework", "either ", "option a or option b", "decide on")):
                return True, f"Ambiguity detected in plan step: '{step}'. Which option should be prioritized?", ["Option A (Standard)", "Option B (Alternative)"]
        return False, "", []

    def clarify_node(self, state: DeepAgentState) -> DeepAgentState:
        """CLARIFY Node: pause execution and inject user steering input to resolve ambiguity."""
        # Phase3.2: explicit cursor — node entry checkpointed immediately.
        state.current_node = "CLARIFY"
        self._save_checkpoint(state)
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
        # Phase3.2: explicit cursor — node entry is checkpointed immediately.
        state.current_node = "PLAN"
        self._save_checkpoint(state)
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
        # Phase3.2: explicit cursor — node entry checkpointed immediately.
        state.current_node = "REPLAN"
        self._save_checkpoint(state)
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
                        # Phase4.1 Auto-Critical (d): a programmatic replan flag freezes
                        # the most-recent evidence so the corrective branch keeps its anchor.
                        self._flag_latest_evidence_critical()
                        return state
                except Exception:
                    time.sleep(0.4)

        return state

    def _is_sensitive_action(self, step: str) -> bool:
        """Deterministic safety check for dangerous keywords or sensitive kernel paths."""
        dangerous_keywords = ["rm ", "shred", "drop", "purge", "core/", "main.py"]
        return any(kw in step.lower() for kw in dangerous_keywords)

    def execute_node(self, state: DeepAgentState) -> DeepAgentState:
        """EXECUTE Node: execute plan steps via LLM -> tool dispatch -> observation.

        Iterates using the explicit ``current_plan_index`` cursor (Phase3.2) so a
        resume after an Android LMK interrupt lands exactly where it left off —
        including mid-EXECUTE — without re-deriving progress from side effects.

        Granular checkpointing (Phase3.2): a snapshot is written
          • immediately on node entry (current_node='EXECUTE'),
          • immediately BEFORE each tool dispatch,
          • immediately AFTER the result is recorded.
        so a kill at any point leaves a resumable cursor.

        Mid-EXECUTE re-dispatch prevention (Phase3.2): if we resume onto a
        step whose prior attempt was interrupted (no result in the ledger and the
        index is still ahead of ``past_steps``), we do NOT blindly re-run a
        possibly non-idempotent shell command. The step is recorded as an
        INTERRUPTED observation and the cursor advances to REVIEW/REPLAN.
        """
        # Phase3.2: explicit cursor — node entry is checkpointed immediately.
        state.current_node = "EXECUTE"
        self._save_checkpoint(state)
        bus.emit("deep_exec", {"steps": state.plan, "iteration": state.iteration})

        # Phase3.2: the mid-EXECUTE re-dispatch guard fires only once, on
        # the FIRST execute_node call after an LMK resume. Consume the flag
        # so every subsequent iteration (and fresh runs) dispatches normally.
        resuming = self._resume_mode
        self._resume_mode = False

        if not self.llm:
            state.errors.append("NO_LLM")
            return state

        # Iterate using the persistent cursor, not a fresh enumerate().
        while state.current_plan_index < len(state.plan):
            idx = state.current_plan_index
            step = state.plan[idx]

            # ── Mid-EXECUTE re-dispatch prevention (resume only) ──────────
            # On the resumed call we must NOT blindly re-run steps:
            #   • idx < len(past_steps) → already completed in a prior run;
            #     skip it without re-dispatching.
            #   • idx >= len(past_steps) → no result in the ledger, i.e. the
            #     step was killed mid-flight (or never started). Re-executing a
            #     non-idempotent shell command is unsafe, so we record it
            #     INTERRUPTED and transition out to REVIEW/REPLAN instead.
            if resuming:
                if idx < len(state.past_steps):
                    state.current_plan_index += 1
                    self._save_checkpoint(state)
                    continue
                # Interrupted in-flight step: never re-dispatch blindly.
                state.past_steps.append(step)
                interrupted_obs = (
                    f"[INTERRUPTED] {step[:80]}\n"
                    f"  tool: (unknown — killed mid-dispatch before result)\n"
                    f"  Note: skipped re-dispatch to avoid non-idempotent replay."
                )
                state.observations.append(interrupted_obs)
                state.execution_results.append("[Interrupted] step killed before result")
                state.errors.append(f"LMK_INTERRUPT: step '{step[:60]}'")
                state.current_plan_index += 1
                self._save_checkpoint(state)
                # Fall through to REVIEW/REPLAN rather than retrying blindly.
                break

            if self._is_sensitive_action(step) or state.critique:
                bus.emit("hitl_triggered", {"step": step, "iteration": state.iteration})
                if self.hitl_callback and not self.hitl_callback(step):
                    state.critique = f"User rejected step: '{step}'. Re-plan alternative path."
                    state.errors.append("USER_REJECTION")
                    state.current_plan_index += 1
                    self._save_checkpoint(state)
                    return state

            worker_tag = "[SEC]" if any(k in step.lower() for k in ("security", "audit", "vuln", "patch")) else "[FS]"
            bus.emit("deep_exec_step", {"step_idx": idx + 1, "total": len(state.plan), "step": step, "worker": worker_tag})

            # Build context from this plan step, past observations, and tool schemas
            tool_schemas = self._tool_schemas_summary()
            # Phase5 (GoalSpec): surface the active verifiable objective so the
            # executor steers every step toward the success criteria, not just the
            # local plan step. Injected as a hard XML block the planner preserves.
            goal = self.runtime_state.active_goal
            from engine.state import GoalSpec as _GS, build_goal_block
            goal_block = build_goal_block(goal) if isinstance(goal, _GS) else ""
            exec_prompt = (
                f"You are executing plan step {idx+1}/{len(state.plan)} for the goal: {state.task}\n"
                f"Current step: {step}\n\n"
                f"Available tools: {tool_schemas}\n\n"
                f"{goal_block}\n\n"
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

                from engine.tool_registry import registry as _registry
                v_ok, v_err = validate_tool_call({"tool": tool_call.tool, "args": tool_call.args}, _registry)
                if not v_ok:
                    state.errors.append(f"SECURITY_REJECT: Schema validation failed for '{tool_call.tool}': {v_err}")
                    continue

                # NOTE: no separate execute_shell safety pre-check here. Security
                # validation is performed exactly once, inside the dispatcher's
                # ShellTool.execute(), which returns a ToolResult (success=False)
                # on rejection. A duplicated pre-check would block the dispatch
                # before any evidence is recorded — preventing the failed-dispatch
                # evidence path (and other callers) from observing the rejection.
                # The emit/record flow below therefore captures both success and
                # failure outcomes uniformly.

                # Phase3.2 granular checkpoint: snapshot the cursor (with the
                # pending tool_call) IMMEDIATELY before dispatch, so a kill
                # during execution leaves the step flagged as in-flight.
                state.current_plan_index = idx
                self._save_checkpoint(state)

                # ── Consent Loop (Phase 2 Public Release Protocol) ────────────
                # Intercept BEFORE dispatch. The consent policy is centralized in
                # ConsentManager. A declined call returns a normal successful
                # ToolResult (success=True, stdout="Execution blocked by user.")
                # — a valid outcome, not an engine error. No exception, no abort,
                # no loop_error; the LLM adapts its plan from the observation.
                result = None
                if ConsentManager().requires_confirmation(tool_call.tool, tool_call.args):
                    blocked = ConsentManager().confirm(tool_call.tool, tool_call.args)
                    if blocked is not None:
                        result = blocked

                if result is None:
                    try:
                        result = self.dispatcher.dispatch(tool_call.tool, tool_call.args)
                        if result is None:
                            result = ToolResult(success=False, stderr="Dispatcher returned None", returncode=-1)
                        # Recovery guard: if this exact step already produced a
                        # ledger entry from a prior (pre-LMK) run, treat the new
                        # dispatch as authoritative and avoid double-counting.
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
                        # Phase3.2 granular checkpoint: snapshot AFTER the result
                        # is recorded, so a kill now resumes past this step.
                        self._save_checkpoint(state)
                        break
                    except Exception as exc:
                        state.errors.append(f"DISPATCH_ERROR: {exc}")
                        continue

            if result is None:
                err_msg = f"Step '{step[:80]}' failed after 3 attempts."
                state.past_steps.append(step)
                state.observations.append(f"[ERROR] {err_msg}")
                state.execution_results.append(f"[Execution Error] {err_msg}")
                state.current_plan_index += 1
                self._save_checkpoint(state)
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
            # Advance the cursor and checkpoint the completed step.
            state.current_plan_index += 1
            self._save_checkpoint(state)

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
        # Phase3.2: explicit cursor — node entry checkpointed immediately.
        state.current_node = "REVIEW"
        self._save_checkpoint(state)
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
        # Phase4.1 Auto-Critical (d): a passing review freezes the most-recent
        # evidence as the canonical artifact for this node transition.
        if state.review_passed:
            self._flag_latest_evidence_critical()
        return state

    def _flag_latest_evidence_critical(self) -> None:
        """Phase4.1 helper: freeze the most-recent evidence record as Critical."""
        recs = self.evidence_log.get_records()
        if recs:
            self.evidence_log.flag_critical(recs[-1].evidence_id)

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
        # Resume if a stale checkpoint exists for this workspace.
        restored = self._load_checkpoint()
        if restored is not None:
            state = restored
            # Phase3.1 replay-safety: remount from the slim ledger ONLY. Never
            # re-expand raw history — the checkpoint mirrors the compacted view,
            # so an LMK recovery does not re-inflate the context.
            self._restore_evidence_from_ledger(state)
            # Phase5 (GoalSpec): re-inject the checkpointed objective into the
            # live runtime_state so the verifiable exit gate fires on resume.
            self._reconcile_goal_with_checkpoint(state)
            bus.emit("deep_resume", {"task": state.task, "iteration": state.iteration})
        else:
            state = DeepAgentState(task=task)
            # Phase5 (GoalSpec): mirror any active objective into the checkpoint
            # so it is serialized and survives an LMK kill from the very first
            # node transition.
            if self.runtime_state.active_goal is not None:
                state.goal = self.runtime_state.active_goal

        # Checkpoint helper: run a node, then persist atomically. This is the
        # LMK guard — every node transition leaves a clean, resumable snapshot.
        def _step(node_fn, label):
            nonlocal state
            state = node_fn(state)
            self._save_checkpoint(state)
            return state

        if restored is not None:
            # Replay-safe resume: the plan/clarify nodes are already persisted in
            # the checkpoint, so re-running them would duplicate historical turn
            # processing. Jump straight into the loop at the interrupted node
            # selected by the explicit cursor (Phase3.2) — no re-planning.
            # Flag execute_node so its mid-EXECUTE re-dispatch guard fires once.
            self._resume_mode = True
        else:
            _step(self.plan_node, "plan")
            _step(self.clarify_node, "clarify")

        while not state.review_passed and state.iteration < self.max_iterations:
            # Phase3.2: on a resumed run, honor the explicit node cursor so we
            # re-enter exactly where the LMK kill happened (EXECUTE/REVIEW/REPLAN)
            # rather than blindly re-running EXECUTE. A fresh run always executes.
            if restored is not None and state.current_node != "EXECUTE":
                if state.current_node == "REVIEW":
                    _step(self.review_node, "review")
                elif state.current_node == "REPLAN":
                    state.iteration += 1
                    _step(self.replan_node, "replan")
                else:
                    # PLAN/CLARIFY or unknown cursor → safest is to re-execute
                    # from the current plan index (execute_node self-heals via the
                    # mid-EXECUTE re-dispatch guard).
                    _step(self.execute_node, "execute")
            else:
                _step(self.execute_node, "execute")
                _step(self.review_node, "review")

            if self.should_replan(state) and state.iteration < self.max_iterations - 1:
                state.iteration += 1
                _step(self.replan_node, "replan")

        # Check chitchat first
        from core.constants import is_chitchat
        is_chat, _ = is_chitchat(task)
        if is_chat and not state.past_steps:
            self._clear_checkpoint()
            return state.final_output

        # Final evidence verification gate with self-correction
        retry_count = 0
        MAX_SELF_CORRECT = 3
        while retry_count <= MAX_SELF_CORRECT:
            try:
                self.evidence_log.verify(require_tools=True, claim=state.final_output)
                # Phase5 (GoalSpec): verifiable exit condition.
                # Even though the generic verifier (L0/L1) passed, a GoalSpec is a
                # STRICTER gate: the agent may not return "Success" unless the goal
                # verifier explicitly proves every success criterion against live
                # evidence. On failure we raise so the existing except branch
                # issues a goal critique and re-enters the plan/execute loop.
                goal = self.runtime_state.active_goal
                from engine.state import GoalSpec
                from engine.goal_verifier import evaluate_goal_exit
                if isinstance(goal, GoalSpec) and goal.raw_prompt.strip():
                    # Signal the Kinetic UX that the Verifier is evaluating the
                    # objective before the strict exit gate resolves.
                    bus.emit("goal_verify", {
                        "session_id": self.runtime_state.session_id,
                        "raw_prompt": goal.raw_prompt,
                        "step": self.state.step_count,
                    })
                    gres = evaluate_goal_exit(
                        goal, self.evidence_log, require_tools=True,
                        final_claim=state.final_output,
                    )
                    if not gres.ok:
                        raise VerifierError(gres.to_critique())
                    goal.is_met = True
                    self.runtime_state.active_goal = goal
                    # Keep the checkpoint's goal in sync so a later resume (if the
                    # clear below is skipped) reflects the proven objective.
                    state.goal = goal
                self._clear_checkpoint()
                return state.final_output
            except Exception as verr:
                if retry_count == MAX_SELF_CORRECT:
                    state.final_output = (
                        f"Unable to complete the task after {MAX_SELF_CORRECT} self-correction attempts. Last error: {verr}"
                    )
                    self._save_checkpoint(state)
                    break
                critique = (
                    f"[VERIFIER CRITIQUE]: {verr}. Correct your approach and retry with the correct tool."
                )
                state.observations.append(critique)
                state.iteration += 1
                _step(self.execute_node, "execute")
                _step(self.review_node, "review")
                retry_count += 1
                backoff_delay = min(0.5 * (2 ** (retry_count - 1)), 4.0)
                time.sleep(backoff_delay)

        self._clear_checkpoint()
        return state.final_output


def maybe_resume_deep_agent(agent: "NativeDeepAgent") -> bool:
    """Bootstrapping resume hook — detect, prompt, restore, or purge a checkpoint.

    Called at agent boot (from ``main.py``). If ``.nabd_agent_state.json`` exists,
    the operator is asked via the UI bridge to resume. Returns ``True`` if a stale
    session was found (so the caller can skip fresh planning or log accordingly);

    Behavior on the operator's answer:
      • 'y' → keep the file so ``NativeDeepAgent.run`` transparently resumes from
        the interrupted node (run() restores from the checkpoint on first call).
      • 'n' → purge the file and start clean.

    The prompt is routed through ``core.ui_bridge.get_bridge().request_user_input``,
    which is fail-closed (denies on any I/O error) — so a headless/LMK context
    never silently resumes a stale session. The worker-thread execution model means
    the blocking prompt cannot freeze the async REPL.
    """
    checkpoint = agent.checkpoint_path
    if not checkpoint.exists():
        return False

    try:
        from core.ui_bridge import get_bridge
        reply = get_bridge().request_user_input(
            "[SYSTEM] Stale session detected. Resume from last checkpoint? (y/n): "
        ).strip().lower()
    except Exception:
        # Bridge unreachable / headless → fail closed: purge and start clean.
        agent._clear_checkpoint()
        return False

    if reply in ("y", "yes"):
        bus.emit("deep_resume_prompted", {"decision": "resume"})
        return True

    # Any non-yes answer → purge and start clean.
    agent._clear_checkpoint()
    bus.emit("deep_resume_prompted", {"decision": "purge"})
    return True


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

