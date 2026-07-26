"""Stage 6 — Multi-Agent Orchestration (Orchestrator-Workers pattern).

A self-contained orchestration layer in `core/` built on the existing
smolagents `CodeAgent` stack. The OrchestratorAgent owns a shared execution
scratchpad and routes the task to a specialized CoderAgent, then hands the
emitted payload to a VerifierAgent (the Stage 4 strict auditor). Rejections
loop back to the CoderAgent for a rewrite (up to max_retries).

This is the SINGLE authoritative orchestration layer (the legacy
multi_agent/ package has been removed). All cross-agent handoffs are
broadcast through the safe UIBridge fan-out so logs capture the loop.

ARCHITECTURAL CONSTRAINT (Phase 6.1 — Instability reduction):
  Module-level non-stdlib imports are kept to an absolute minimum (Fan-Out=2)
  to achieve Instability <= 0.5. All other external dependencies are imported
  lazily inside the method/function that needs them.
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

# ── Minimal non-stdlib module-level imports (Fan-Out = 2) ─────────────────────
# These symbols are used across multiple methods. All other dependencies are
# imported lazily inside the scope that needs them (see _lazy_* helpers below).
from core.agent_manager import MemoryStore
from core.kernel.events import bus

# Local package roots that are NOT third-party (treat as internal, never
# route through uv). Extend here if more first-party namespaces appear.
_LOCAL_NAMESPACES = {"core", "skills", "engine", "ui", "tools", "smolagents"}


# ── Lazy import helpers ──────────────────────────────────────────────────────
# Each function caches its result so the import penalty is paid at most once
# per process.  This is the DI seam: callers never import the dependency at
# module level, and swapping implementations requires editing only the helper.

def _lazy_get_secure_model():
    from llm_router import get_secure_model as _m
    return _m


def _lazy_safe_sandbox():
    from core.self_refinement import SafeExecutionSandbox as _s
    return _s


def _lazy_context_manager():
    from core.context_manager import RepositoryContextManager as _r
    return _r


def _lazy_uv_manager():
    from core.uv_isolation_manager import UvIsolationManager as _u
    return _u


def _lazy_bridge():
    from core.ui_bridge import get_bridge as _b
    return _b


def _broadcast_orch(milestone: str, detail: str = "") -> None:
    """Emit an orchestration milestone through the fail-safe UI bridge."""
    try:
        _lazy_bridge()._notify_observers(
            "on_status_changed", f"ORCH_{milestone}", detail
        )
    except Exception:
        pass


def _broadcast_sandbox(milestone: str, detail: str = "") -> None:
    """Emit a self-refinement/sandbox milestone through the fail-safe UI bridge."""
    try:
        _lazy_bridge()._notify_observers(
            "on_status_changed", f"SANDBOX_{milestone}", detail
        )
    except Exception:
        pass


class OrchestratorAgent:
    """Coordinates the Coder -> Verifier worker loop over a shared scratchpad."""

    def _extract_external_deps(self, code_str: str) -> List[str]:
        """Return top-level third-party module names imported by ``code_str``.

        Cross-references imports against sys.stdlib_module_names and the known
        first-party namespaces; anything else is an external dependency that
        must run in an isolated uv environment.
        """
        try:
            found = re.findall(r"^(?:import|from)\s+([a-zA-Z0-9_]+)", code_str, re.M)
            stdlib = getattr(sys, "stdlib_module_names", set())
            externals = []
            for name in found:
                if name in stdlib:
                    continue
                if name in _LOCAL_NAMESPACES:
                    continue
                if name not in externals:
                    externals.append(name)
            return externals
        except Exception:
            return []

    def __init__(self, model: Any | None = None) -> None:
        get_secure_model = _lazy_get_secure_model()
        self._model = model or get_secure_model()

        from core.kernel.security import get_workspace_root
        self.workspace_dir = str(get_workspace_root())
        from core.agents.coder_agent import CoderAgent
        self.coder = CoderAgent(self._model)
        from core.agents.verifier_agent import VerifierAgent
        self.verifier = VerifierAgent(self._model)
        self.scratchpad: Dict[str, Any] = {
            "goal": "",
            "history": "",
            "payload": "",
            "attempts": 0,
            "rejections": [],
        }

    def _build_history_context(self) -> str:
        """Pull lessons/failures from PersistentMemory for alignment."""
        lessons = MemoryStore.lessons_learned
        failures = MemoryStore.failure_logs
        ctx = ""
        if lessons:
            ctx += "LESSONS LEARNED (apply):\n" + "\n".join(f"- {l}" for l in lessons) + "\n"
        if failures:
            ctx += "FAILURES TO AVOID:\n" + "\n".join(
                f"- {f['action']}: {f['error']}" for f in failures
            ) + "\n"
        return ctx

    def coordinate(self, task: str, max_retries: int = 3) -> Dict[str, Any]:
        """Run the Orchestrator-Workers loop and return a status dict."""
        RepositoryContextManager = _lazy_context_manager()
        UvIsolationManager = _lazy_uv_manager()
        SafeExecutionSandbox = _lazy_safe_sandbox()

        self.scratchpad["goal"] = task
        self.scratchpad["history"] = self._build_history_context()
        _ctx = RepositoryContextManager()
        _task_id = RepositoryContextManager.task_id_for(task)
        _ctx.update_state(_task_id, "In Progress", {"attempts": 0})

        _broadcast_orch("DELEGATE", "task -> CoderAgent")
        brief = (self.scratchpad["history"] + "\n---\nTASK:\n" + task).strip()

        last_payload = ""
        status = "failed"

        for attempt in range(1, max_retries + 1):
            self.scratchpad["attempts"] = attempt

            _broadcast_orch("CODER_START", f"attempt {attempt}/{max_retries}")
            bus.emit("agent_handoff", {
                "from_role": "ORCHESTRATOR",
                "to_role": "CODER",
                "payload": task,
            })
            last_payload = self.coder.code(brief)
            self.scratchpad["payload"] = last_payload
            _broadcast_orch("CODER_SUCCESS", f"attempt {attempt}")

            _broadcast_sandbox("TEST_START", f"attempt {attempt}")
            external_deps = self._extract_external_deps(last_payload)

            if external_deps:
                _broadcast_sandbox("TEST_UV", f"attempt {attempt}: deps={external_deps}")
                try:
                    uv_result = UvIsolationManager().run_in_isolated_env(
                        last_payload, dependencies=external_deps, timeout=30.0
                    )
                except Exception as exc:
                    uv_result = {
                        "success": False,
                        "stdout": "",
                        "stderr": f"{type(exc).__name__}: {exc}",
                        "exit_code": -1,
                    }

                if not uv_result["success"]:
                    _broadcast_sandbox("TEST_FAIL", f"attempt {attempt}: uv")
                    error_ctx = uv_result["stderr"] or "unknown uv isolation failure"
                    self.scratchpad["rejections"].append(
                        {"attempt": attempt, "stage": "uv", "reasons": error_ctx[:200]}
                    )
                    MemoryStore.log_failure(f"uv:{task[:80]}", error_ctx[:200])
                    _broadcast_orch("CODER_REWRITE", f"attempt {attempt}: uv fail")
                    brief = (
                        f"PREVIOUS ATTEMPT FAILED IN UV ISOLATION.\n"
                        f"CONCRETE TECHNICAL ERROR:\n{error_ctx}\n\n"
                        f"{brief}"
                    )
                    continue

                _broadcast_sandbox("TEST_PASS", f"attempt {attempt}: uv")
            else:
                sandbox_result = SafeExecutionSandbox.smoke_test_code(last_payload)
                if not sandbox_result["passed"]:
                    _broadcast_sandbox("TEST_FAIL", f"attempt {attempt}")
                    error_ctx = sandbox_result["error"] or "unknown sandbox failure"
                    self.scratchpad["rejections"].append(
                        {"attempt": attempt, "stage": "sandbox", "reasons": error_ctx[:200]}
                    )
                    MemoryStore.log_failure(f"sandbox:{task[:80]}", error_ctx[:200])
                    _broadcast_orch("CODER_REWRITE", f"attempt {attempt}: sandbox fail")
                    brief = (
                        f"PREVIOUS ATTEMPT FAILED THE SANDBOX SMOKE TEST.\n"
                        f"CONCRETE TECHNICAL ERROR:\n{error_ctx}\n\n"
                        f"{brief}"
                    )
                    continue

                _broadcast_sandbox("TEST_PASS", f"attempt {attempt}")

            _broadcast_orch("VERIFIER_EVALUATE", f"attempt {attempt}")
            bus.emit("agent_handoff", {
                "from_role": "CODER",
                "to_role": "AUDITOR",
                "payload": last_payload[:2000],
            })
            verdict = self.verifier.evaluate(task, last_payload)

            if verdict["passed"]:
                _broadcast_orch("VERIFIER_PASS", f"attempt {attempt}")
                status = "verified"
                self._persist_lesson_if_any(last_payload, task)
                break

            reasons = "; ".join(verdict.get("reasons", []))
            self.scratchpad["rejections"].append({"attempt": attempt, "reasons": reasons})
            try:
                _ctx.record_lesson(
                    _task_id,
                    failed_code=last_payload,
                    traceback_str=str(verdict.get("reasons", [])),
                    fix_applied=str(verdict.get("fix_hint", "")),
                )
            except Exception:
                pass
            MemoryStore.log_failure(f"orch:{task[:80]}", reasons)
            _broadcast_orch("VERIFIER_REJECT", f"attempt {attempt}: {reasons}")
            bus.emit("agent_handoff", {
                "from_role": "AUDITOR",
                "to_role": "CODER",
                "payload": reasons,
            })
            brief = (
                f"PREVIOUS ATTEMPT REJECTED BY VERIFIER.\n"
                f"REASONS: {reasons}\n"
                f"FIX HINT: {verdict.get('fix_hint', '')}\n\n"
                f"{brief}"
            )

        if status != "verified":
            _broadcast_orch("EXHAUSTED", f"retries={max_retries}")
            try:
                _ctx.update_state(
                    _task_id,
                    "Escalated to Human",
                    {"attempts": self.scratchpad["attempts"], "stage": "exhausted"},
                )
            except Exception:
                pass
        else:
            try:
                _ctx.update_state(
                    _task_id,
                    "Completed",
                    {"attempts": self.scratchpad["attempts"]},
                )
            except Exception:
                pass

        return {
            "status": status,
            "final_payload": last_payload,
            "attempts": self.scratchpad["attempts"],
            "rejections": self.scratchpad["rejections"],
            "scratchpad": self.scratchpad,
        }

    def dispatch_parallel_tasks(
        self, tasks: List[Dict[str, Any]], max_workers: int = 2
    ) -> Dict[str, Any]:
        """Execute a batch of worker tasks concurrently with isolation.

        Each task dict must contain at least:
            task_id:   unique identifier (used as the result key)
            agent_role: 'coder' | 'verifier'
            payload:   input forwarded to the corresponding worker

        Returns a dict mapping each task_id to its execution result. A crash
        in one worker yields a failure payload for that task_id only — the
        rest of the pool continues. All milestones are broadcast safely.
        """
        _broadcast_orch("PARALLEL_START", f"{len(tasks)} tasks / {max_workers} workers")
        results: Dict[str, Any] = {}

        def _run_one(task: Dict[str, Any]) -> Any:
            task_id = task.get("task_id", "unknown")
            try:
                role = task.get("agent_role", "")
                payload = task.get("payload")
                if role == "coder":
                    return self.coder.code(payload)
                if role == "verifier":
                    return self.verifier.evaluate(payload, payload)
                raise ValueError(f"unknown agent_role: {role!r}")
            except Exception as exc:
                return {
                    "task_id": task_id,
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            finally:
                _broadcast_orch("PARALLEL_TASK_DONE", str(task_id))

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_run_one, task): task.get("task_id", "unknown")
                    for task in tasks
                }
                for future in as_completed(futures):
                    tid = futures[future]
                    try:
                        results[tid] = future.result()
                    except Exception as exc:
                        results[tid] = {
                            "task_id": tid,
                            "success": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
        except Exception as exc:
            for task in tasks:
                tid = task.get("task_id", "unknown")
                results.setdefault(
                    tid,
                    {"task_id": tid, "success": False, "error": f"pool error: {exc}"},
                )

        _broadcast_orch("PARALLEL_COMPLETE", f"{len(results)} tasks resolved")
        return results

    def _persist_lesson_if_any(self, payload: str, task: str) -> None:
        try:
            if len(payload) > 50 and (
                "def " in payload or "class " in payload or "import " in payload
            ):
                MemoryStore.add_lesson(f"Orchestrated solution for: {task[:80]}")
        except Exception:
            pass

    def _extract_json_from_llm(self, text: str) -> dict:
        """Helper to extract clean JSON from LLM response text."""
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            if not isinstance(text, str):
                return {"nodes": [], "edges": [], "error": "Invalid response type"}
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
            return {"nodes": [], "edges": [], "error": "Invalid JSON format from LLM"}

    def process_graphify_chunks_parallel(
        self, file_chunks: list, prompt_template: str = "", max_workers: int = 3
    ):
        """Step B2: Dispatch ALL subagents in parallel to process codebase chunks.

        Includes intelligent token-optimization routing (pure-code bypass) and
        LLM extraction.
        """
        results = []
        total_chunks = len(file_chunks)

        extraction_spec_path = os.path.join(self.workspace_dir, "references", "extraction-spec.md")
        extraction_prompt = prompt_template
        if not extraction_prompt and os.path.exists(extraction_spec_path):
            with open(extraction_spec_path, "r", encoding="utf-8") as f:
                extraction_prompt = f.read()

        print(f"🚀 [Dispatcher] Launching {total_chunks} Sub-Agents in PARALLEL mode (Max Workers: {max_workers})...")

        def agent_task(chunk_data):
            chunk_num = chunk_data.get("chunk_num", 0)
            content = chunk_data.get("content", "")
            file_type = chunk_data.get("type", "code")

            if file_type == "code":
                print(f"⏩ [Agent {chunk_num}] Skipping deep extraction for pure-code chunk.")
                return {"chunk_id": chunk_num, "nodes": [], "edges": [], "skipped": True}

            prompt = (
                extraction_prompt.replace("CHUNK_NUM", str(chunk_num))
                .replace("TOTAL_CHUNKS", str(total_chunks))
                .replace("FILE_LIST", content)
                .replace("DEEP_MODE", "true")
            )

            print(f"🧠 [Agent {chunk_num}] Querying LLM for semantic extraction ({file_type})...")

            try:
                llm_engine = getattr(self, "llm_engine", None)
                if llm_engine and hasattr(llm_engine, "generate"):
                    llm_response = llm_engine.generate(prompt)
                elif callable(self._model):
                    llm_response = self._model([{"role": "user", "content": prompt}])
                elif hasattr(self._model, "generate"):
                    llm_response = self._model.generate(prompt)
                else:
                    llm_response = str(self._model)

                parsed_data = self._extract_json_from_llm(llm_response)
                parsed_data["chunk_id"] = chunk_num
                return parsed_data
            except Exception as e:
                print(f"❌ [Agent {chunk_num}] LLM Inference failed: {e}")
                return {"chunk_id": chunk_num, "nodes": [], "edges": [], "error": str(e)}

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_chunk = {executor.submit(agent_task, chunk): chunk for chunk in file_chunks}
                for future in as_completed(future_to_chunk):
                    result = future.result()
                    results.append(result)
                    print(f"✅ [Dispatcher] Agent finished Chunk {result['chunk_id']} successfully!")
        except Exception as e:
            print(f"⚠️ [Dispatcher] Parallel dispatch failed (Resource Exhaustion/OOM): {e}")
            print("🔄 [Dispatcher] Falling back to SERIAL Path (Graceful Fallback)...")
            results = []
            for chunk in file_chunks:
                try:
                    result = agent_task(chunk)
                    results.append(result)
                    chunk_num = chunk.get("chunk_num", 0)
                    chunk_path = os.path.join(self.workspace_dir, "graphify-out", f".graphify_chunk_{chunk_num}.json")
                    os.makedirs(os.path.dirname(chunk_path), exist_ok=True)
                    with open(chunk_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    print(f"✅ [Serial] Agent finished and saved Chunk {chunk_num}")
                except Exception as inner_e:
                    print(f"❌ [Serial] Agent failed on Chunk {chunk.get('chunk_num')}: {inner_e}")

        results.sort(key=lambda x: x.get("chunk_id", 0))
        self._aggregate_graph_results(results)
        return results

    def _aggregate_graph_results(self, all_results: list):
        """Aggregate all subagent graph outputs into a single JSON."""
        final_graph = {"nodes": [], "edges": [], "hyperedges": []}

        for res in all_results:
            final_graph["nodes"].extend(res.get("nodes", []))
            final_graph["edges"].extend(res.get("edges", []))

        output_path = os.path.join(self.workspace_dir, "graphify-out", ".graphify_semantic_new.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_graph, f, ensure_ascii=False, indent=2)

        print(f"🎯 [Aggregation] Successfully merged all chunks into {output_path}!")


MultiAgentOrchestrator = OrchestratorAgent


# ── NabdOS Deterministic DAG Refactoring Bridge ──────────────────────────────

def _lazy_dag_context():
    from core.dag.context import NabdExecutionContext as _c
    return _c


def _lazy_dag_executor():
    from core.dag.executor import NabdDAGExecutor as _e
    return _e


def _lazy_dag_nodes():
    """Lazy-load all DAG node classes at once."""
    from core.dag.nodes.reasoner import ReasonerNode
    from core.dag.nodes.sentinel import SentinelNode
    from core.dag.nodes.executor import ExecutorNode
    from core.dag.nodes.reader import ReaderNode
    from core.dag.nodes.terminal import TerminalNode
    return ReasonerNode, SentinelNode, ExecutorNode, ReaderNode, TerminalNode


class _EndNode:
    """Internal end-of-pipeline sentinel node."""

    def __init__(self):
        self.node_id = "end"

    def execute(self, context: Any) -> None:
        print("\n🎉 [End Node] NabdOS DAG Pipeline Finished!")
        return None


def trigger_nabdos_dag_refactoring(
    llm_engine, workspace_dir, target_files, taste_rules, graphify_tool=None
):
    """Launch the deterministic DAG pipeline for codebase refactoring."""
    print("\n⚔️  Activating NabdOS Deterministic DAG Pipeline (with Spatial Reader)...")

    NabdExecutionContext = _lazy_dag_context()
    NabdDAGExecutor = _lazy_dag_executor()
    ReasonerNode, SentinelNode, ExecutorNode, ReaderNode, TerminalNode = _lazy_dag_nodes()

    context = NabdExecutionContext(
        workspace_dir=workspace_dir,
        target_files=target_files,
        taste_rules=taste_rules,
    )
    engine = NabdDAGExecutor()
    engine.register_node(ReaderNode(graphify_tool=graphify_tool))
    engine.register_node(ReasonerNode(llm_engine=llm_engine))
    engine.register_node(SentinelNode())
    engine.register_node(ExecutorNode())
    engine.register_node(TerminalNode())
    engine.register_node(_EndNode())

    return engine.execute(start_node_id="reader_node", context=context)
