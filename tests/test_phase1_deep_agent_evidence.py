"""Phase 1 — Single evidence brain for NativeDeepAgent.

Verifies:
  1. execute_node records evidence after every successful dispatch.
  2. execute_node records evidence with success=False after a failed dispatch.
  3. Record format matches what ExecutionLoop produces (compatible with Verifier).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from typing import Any

from engine.deep_agent import NativeDeepAgent, DeepAgentState
from engine.state import RuntimeState
from engine.dispatcher import Dispatcher
from core.evidence import EvidenceLog
from tools.models import ToolResult


def _stub_dispatcher(result: ToolResult | None = None) -> Dispatcher:
    """Return a Dispatcher whose dispatch() always returns the given result."""
    if result is None:
        result = ToolResult(success=True, stdout="ok")
    state = RuntimeState(session_id="test-p1")

    class StubDispatcher(Dispatcher):
        def dispatch(self, tool_name: str, kwargs: dict, timeout: int = 30) -> ToolResult:
            if result is None:
                return ToolResult(success=False, stderr="simulated failure", returncode=-1)
            return result

    return StubDispatcher(state)


def _stub_llm(json_response: str) -> callable:
    """Return an LLM callable that always returns the given string."""
    def llm_fn(messages: list[dict[str, Any]]) -> str:
        return json_response
    return llm_fn


def test_deep_agent_records_evidence_after_successful_dispatch():
    """A successful tool dispatch must produce an EvidenceRecord with success=True."""
    llm = _stub_llm('```json\n{"tool": "execute_shell", "args": {"command": "echo hello"}}\n```')
    agent = NativeDeepAgent(
        runtime_state=RuntimeState(session_id="test-p1-s"),
        llm_client=llm,
        dispatcher=_stub_dispatcher(ToolResult(success=True, stdout="hello")),
    )
    state = DeepAgentState(task="say hello")
    state.plan = ["run echo hello"]

    result_state = agent.execute_node(state)

    # Evidence must have been recorded
    records = agent.evidence_log.records
    assert len(records) >= 1, f"Expected at least 1 evidence record, got {len(records)}"

    rec = list(records.values())[0]
    assert rec.success is True, f"Expected success=True, got {rec.success}"
    assert rec.tool == "execute_shell", f"Expected tool='execute_shell', got {rec.tool}"
    assert rec.evidence_type == "shell", f"Expected evidence_type='shell', got {rec.evidence_type}"
    assert rec.evidence_id.startswith("E-"), f"Expected evidence_id like E-*, got {rec.evidence_id}"


def test_deep_agent_records_evidence_after_failed_dispatch():
    """A failed tool dispatch must produce an EvidenceRecord with success=False."""
    llm = _stub_llm('```json\n{"tool": "execute_shell", "args": {"command": "invalid-command"}}\n```')
    agent = NativeDeepAgent(
        runtime_state=RuntimeState(session_id="test-p1-f"),
        llm_client=llm,
        dispatcher=_stub_dispatcher(ToolResult(success=False, stderr="command not found", returncode=127)),
    )
    state = DeepAgentState(task="run invalid command")
    state.plan = ["run it"]

    result_state = agent.execute_node(state)

    records = agent.evidence_log.records
    assert len(records) >= 1, f"Expected at least 1 evidence record, got {len(records)}"

    rec = list(records.values())[0]
    assert rec.success is False, f"Expected success=False, got {rec.success}"
    assert rec.tool == "execute_shell"


def test_deep_agent_record_format_matches_loop_record():
    """Deep agent records must have the same shape as loop records (Verifier-compatible)."""
    llm = _stub_llm('```json\n{"tool": "execute_shell", "args": {"command": "ls -la"}}\n```')

    # Create a dispatcher that records what it dispatches so both paths are comparable
    dispatched_calls = []

    class TrackingDispatcher(Dispatcher):
        def dispatch(self, tool_name: str, kwargs: dict, timeout: int = 30) -> ToolResult:
            dispatched_calls.append((tool_name, kwargs))
            return ToolResult(success=True, stdout="file1.txt  file2.txt")

    state = RuntimeState(session_id="test-p1-format")
    agent = NativeDeepAgent(
        runtime_state=state,
        llm_client=llm,
        dispatcher=TrackingDispatcher(state),
    )
    agent_state = DeepAgentState(task="list files")
    agent_state.plan = ["list current directory"]
    agent.execute_node(agent_state)

    assert len(dispatched_calls) >= 1
    tool_name, tool_args = dispatched_calls[0]

    # Now simulate what loop.py would record for the same call
    loop_log = EvidenceLog()
    cmd_summary = (
        tool_args.get("command")
        or tool_args.get("path")
        or tool_args.get("query")
        or str(tool_args)[:60]
    )
    loop_log.record(
        tool=tool_name,
        command_or_path=cmd_summary,
        success=True,
        output_snippet="file1.txt  file2.txt",
    )

    # Compare the shape: both use the same record() API, so they must
    # produce records the Verifier can consume.
    agent_rec = list(agent.evidence_log.records.values())[0]
    loop_rec = list(loop_log.records.values())[0]

    # Both records must have all fields the Verifier checks
    assert agent_rec.evidence_id.startswith("E-")
    assert loop_rec.evidence_id.startswith("E-")
    assert agent_rec.tool == loop_rec.tool
    assert agent_rec.evidence_type == loop_rec.evidence_type
    assert agent_rec.command_or_path == loop_rec.command_or_path
    assert agent_rec.success == loop_rec.success
    # output_snippet may differ in length (deep agent caps at 500, loop at 200) — but both exist
    assert agent_rec.output_snippet
    assert loop_rec.output_snippet


def test_deep_agent_multiple_steps_produce_multiple_records():
    """When execute_node runs multiple plan steps, each must produce its own record."""
    counter = [0]  # mutable box for closure

    class CountingDispatcher(Dispatcher):
        def dispatch(self, tool_name: str, kwargs: dict, timeout: int = 30) -> ToolResult:
            counter[0] += 1
            return ToolResult(success=True, stdout=f"result-{counter[0]}")

    state = RuntimeState(session_id="test-p1-multi")
    llm = _stub_llm('```json\n{"tool": "execute_shell", "args": {"command": "echo step"}}\n```')
    agent = NativeDeepAgent(
        runtime_state=state,
        llm_client=llm,
        dispatcher=CountingDispatcher(state),
    )
    agent_state = DeepAgentState(task="multi step task")
    agent_state.plan = ["step one", "step two", "step three"]

    agent.execute_node(agent_state)

    assert counter[0] == 3, f"Expected 3 dispatches, got {counter[0]}"
    assert len(agent.evidence_log.records) == 3, (
        f"Expected 3 evidence records, got {len(agent.evidence_log.records)}"
    )


def test_no_dispatch_no_record():
    """When LLM returns no tool call (extract_command returns None), no evidence is recorded."""
    llm = _stub_llm("I don't need a tool for that.")

    class FailDispatcher(Dispatcher):
        def dispatch(self, tool_name: str, kwargs: dict, timeout: int = 30) -> ToolResult:
            raise AssertionError("dispatch() should never be called")

    state = RuntimeState(session_id="test-p1-none")
    agent = NativeDeepAgent(
        runtime_state=state,
        llm_client=llm,
        dispatcher=FailDispatcher(state),
    )
    agent_state = DeepAgentState(task="chitchat")
    agent_state.plan = ["say something without tools"]
    agent.execute_node(agent_state)

    # No dispatch happened, so no evidence should be recorded
    assert len(agent.evidence_log.records) == 0, (
        f"Expected 0 records (no dispatch), got {len(agent.evidence_log.records)}"
    )


if __name__ == "__main__":
    test_deep_agent_records_evidence_after_successful_dispatch()
    test_deep_agent_records_evidence_after_failed_dispatch()
    test_deep_agent_record_format_matches_loop_record()
    test_deep_agent_multiple_steps_produce_multiple_records()
    test_no_dispatch_no_record()
    print("All Phase 1 tests passed.")
