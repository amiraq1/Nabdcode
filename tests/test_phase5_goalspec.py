"""GoalSpec + verifiable /goal exit-condition tests (Phase 5 — Product track).

Verifies:
  1. GoalSpec dataclass shape + serialization round-trip.
  2. parse_goal_command() handles ``/goal <desc>`` and ``/goal <desc> || <criteria>``.
  3. build_goal_block() renders the <active_goal> guard and is empty when no goal.
  4. goal_verifier.evaluate_goal_exit() fails closed (no evidence / L1 fail) and
     passes only when criteria are anchored to live evidence.
  5. ExecutionLoop.run() enforces the gate: with an active goal and no matching
     evidence, the loop emits loop_completed reason="goal_not_met" (never a false
     "Success"), and injects the <active_goal> block into the compacted context.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.state import GoalSpec, parse_goal_command, build_goal_block
from engine.goal_verifier import evaluate_goal_exit
from engine.loop import ExecutionLoop
from engine.state import RuntimeState
from core.evidence import EvidenceLog
from tools.models import ToolResult


# ── GoalSpec model ───────────────────────────────────────────────────────

def test_goalspec_defaults_is_met_false():
    g = GoalSpec(raw_prompt="do the thing", success_criteria="thing is done")
    assert g.is_met is False
    assert g.raw_prompt == "do the thing"
    assert g.success_criteria == "thing is done"


def test_goalspec_round_trip():
    g = GoalSpec(raw_prompt="x", success_criteria="y", is_met=True)
    d = g.to_dict()
    g2 = GoalSpec.from_dict(d)
    assert g2.raw_prompt == "x"
    assert g2.success_criteria == "y"
    assert g2.is_met is True


# ── parse_goal_command ───────────────────────────────────────────────────

def test_parse_goal_simple():
    g = parse_goal_command("/goal write a parser for foo")
    assert g is not None
    assert g.raw_prompt == "write a parser for foo"
    assert g.success_criteria is None
    assert g.is_met is False


def test_parse_goal_explicit_criteria():
    g = parse_goal_command("/goal add feature X || tests pass and lint clean")
    assert g is not None
    assert g.raw_prompt == "add feature X"
    assert g.success_criteria == "tests pass and lint clean"


def test_parse_goal_non_command_returns_none():
    assert parse_goal_command("just a normal prompt") is None
    assert parse_goal_command("/goal") is None  # empty body = no-op


def test_parse_goal_multiline_criteria():
    g = parse_goal_command("/goal Fix database bug\nCriteria:\n- All tests pass\n- No leaks")
    assert g is not None
    assert g.raw_prompt == "Fix database bug"
    assert g.success_criteria == "- All tests pass\n- No leaks"


def test_parse_goal_flags_criteria():
    g = parse_goal_command('/goal add feature X --criteria "tests pass"')
    assert g is not None
    assert g.raw_prompt == "add feature X"
    assert g.success_criteria == "tests pass"

    g2 = parse_goal_command('/goal -c "tests pass" add feature X')
    assert g2 is not None
    assert g2.raw_prompt == "add feature X"
    assert g2.success_criteria == "tests pass"


def test_skill_goal_binding():
    from core.skills import Skill
    s = Skill(
        name="secure-audit",
        description="Audit project security",
        goal="Audit project security",
        success_criteria="No high severity CVEs found",
    )
    assert s.goal == "Audit project security"
    assert s.success_criteria == "No high severity CVEs found"


# ── build_goal_block ─────────────────────────────────────────────────────

def test_build_goal_block_renders_guard():
    g = GoalSpec(raw_prompt="ship the widget", success_criteria="widget shipped")
    block = build_goal_block(g)
    assert "<active_goal" in block
    assert "ship the widget" in block
    assert "widget shipped" in block


def test_build_goal_block_empty_when_no_goal():
    assert build_goal_block(None) == ""
    assert build_goal_block(GoalSpec()) == ""


# ── goal_verifier: fail-closed ───────────────────────────────────────────

def test_goal_verifier_no_goal_short_circuits():
    log = EvidenceLog()
    res = evaluate_goal_exit(None, log)
    assert res.goal_active is False
    assert res.ok is True


def test_goal_verifier_no_evidence_fails():
    log = EvidenceLog()
    g = GoalSpec(raw_prompt="prove X works", success_criteria="X produces output")
    res = evaluate_goal_exit(g, log)
    assert res.goal_active is True
    assert res.ok is False
    assert any("No verified evidence" in f for f in res.findings)


def test_goal_verifier_criteria_anchored_passes():
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="grep X file.py",
               success=True, output_snippet="X found in file.py line 12")
    g = GoalSpec(raw_prompt="prove X works", success_criteria="X found in file.py")
    res = evaluate_goal_exit(g, log)
    assert res.ok is True


def test_goal_verifier_criteria_not_anchored_fails():
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="ls", success=True,
               output_snippet="file.py")
    g = GoalSpec(raw_prompt="prove widget exists", success_criteria="widget.py exists")
    res = evaluate_goal_exit(g, log)
    assert res.ok is False


# ── ExecutionLoop verifiable exit enforcement ────────────────────────────

def test_loop_injects_active_goal_into_context():
    """The <active_goal> block must appear in the compacted messages."""
    state = RuntimeState(session_id="g-ctx")
    goal = GoalSpec(raw_prompt="verify config", success_criteria="config validated")
    state.active_goal = goal
    loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
    compacted = loop._inject_runtime_context(loop._compact_messages(state.get_messages()))
    joined = "\n".join(str(m.get("content", "")) for m in compacted)
    assert "<active_goal" in joined
    assert "verify config" in joined


def test_loop_blocks_false_success_when_goal_unmet():
    """With an active goal and no evidence, the loop must NOT emit a generic
    success termination — it must emit loop_completed reason='goal_not_met'."""
    events = []
    from core.kernel.events import bus
    bus.subscribe("loop_completed", lambda p: events.append(p))

    state = RuntimeState(session_id="g-fail")
    state.active_goal = GoalSpec(
        raw_prompt="prove the server boots", success_criteria="server responds 200"
    )

    # LLM alternates: first emits a (rejected) tool call, then a no-tool claim
    # so we reach the verifiable-exit gate rather than the repetition guard.
    calls = {"n": 0}
    def _provider(msgs):
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            return '```json\n{"tool": "execute_shell", "args": {"command": "curl server"}}\n```'
        return "I believe the server is up now."
    loop = ExecutionLoop(
        state=state,
        llm_provider=_provider,
        evidence_log=EvidenceLog(),
    )
    loop.run("prove the server boots")

    bus.unsubscribe("loop_completed", events[0]) if events else None
    assert events, "expected a loop_completed event"
    reasons = [e.get("reason") for e in events]
    assert "no_tool_call" not in reasons, "goal must block a false success"
    assert "goal_not_met" in reasons, "goal gate must emit goal_not_met"


if __name__ == "__main__":
    for fn in [
        test_goalspec_defaults_is_met_false,
        test_goalspec_round_trip,
        test_parse_goal_simple,
        test_parse_goal_explicit_criteria,
        test_parse_goal_multiline_criteria,
        test_parse_goal_flags_criteria,
        test_skill_goal_binding,
        test_parse_goal_non_command_returns_none,
        test_build_goal_block_renders_guard,
        test_build_goal_block_empty_when_no_goal,
        test_goal_verifier_no_goal_short_circuits,
        test_goal_verifier_no_evidence_fails,
        test_goal_verifier_criteria_anchored_passes,
        test_goal_verifier_criteria_not_anchored_fails,
        test_loop_injects_active_goal_into_context,
        test_loop_blocks_false_success_when_goal_unmet,
    ]:
        fn()
        print("ok", fn.__name__)
    print("All GoalSpec tests passed.")
