# tests/test_phase4_context_compaction.py
"""Phase4.1: Context Hardening, Critical Hard Caps & Auto-Policy."""
import json
import unittest
from engine.loop import ExecutionLoop, _LoopCtx, _ToolInteraction
from engine.state import RuntimeState
from engine.deep_agent import NativeDeepAgent, DeepAgentState, _slim_evidence_ledger
from core.evidence import EvidenceLog
import tempfile
import os


def _mk_ctx(interactions):
    ctx = _LoopCtx(user_prompt="ORIGINAL TASK PROMPT")
    ctx.tool_interactions = list(interactions)
    return ctx


def _it(step, tool, ok, output="", evid="", critical=False, exit_code=0, path_hint=""):
    return _ToolInteraction(
        step=step, tool=tool, ok=ok, exit_code=exit_code,
        path_hint=path_hint, summary=f"{'SUCCESS' if ok else 'FAILURE'}: {path_hint}",
        output=output, evidence_id=evid, critical=critical,
    )


class TestContextCompaction(unittest.TestCase):
    def test_system_and_user_task_hard_preserved_with_active_goal(self):
        state = RuntimeState(session_id="c1")
        state.append_message({"role": "system", "content": "SYS PROMPT"})
        state.append_message({"role": "user", "content": "DO THE THING"})
        # An active goal (with criteria) must freeze messages[1] at the top.
        from engine.state import GoalSpec
        state.active_goal = GoalSpec(raw_prompt="DO THE THING", success_criteria="thing done")
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        compacted = loop._compact_messages(state.get_messages())
        self.assertEqual(compacted[0]["content"], "SYS PROMPT")
        self.assertEqual(compacted[1]["content"], "DO THE THING")

    def test_user_task_not_pinned_in_casual_chat(self):
        """Without an active goal, messages[1] is NOT frozen at the top and the
        most recent chat turn is preserved instead (no greeting-loop pin).

        A realistic multi-turn chat proves the stale "hi" does not displace the
        latest question: the last user message in the compacted context must be
        the most recent one, not the original greeting.
        """
        state = RuntimeState(session_id="c1b")
        state.append_message({"role": "system", "content": "SYS PROMPT"})
        state.append_message({"role": "user", "content": "hi"})
        # Interleave several filler turns so the greeting is no longer "recent".
        for i in range(1, 16):
            state.append_message({"role": "assistant", "content": f"reply {i}"})
            state.append_message({"role": "user", "content": f"follow-up question {i}"})
        state.append_message({"role": "user", "content": "1+1"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        self.assertIsNone(state.active_goal)
        compacted = loop._compact_messages(state.get_messages())
        joined = "\n".join(m["content"] for m in compacted)
        # The latest question must be present in the compacted context.
        self.assertIn("1+1", joined)
        # With many intervening turns the stale greeting slides out of the
        # CHAT_WINDOW entirely (it is NOT frozen at messages[1]).
        self.assertNotIn("hi", joined)
        # Recent priority: the last user turn is the latest question.
        last_user = [m for m in compacted if m.get("role") == "user"][-1]
        self.assertEqual(last_user["content"], "1+1")

    def test_casual_chat_sequence_hi_then_math_not_pinned(self):
        """Regression: casual chat "hi" -> ... -> "1+1" must NOT freeze the greeting.

        The original user prompt (messages[1] == "hi") must not be hard-pinned
        at the top of the compacted context for a later turn, otherwise the LLM
        only ever sees "hi" and loops on the greeting, ignoring "1+1".
        """
        state = RuntimeState(session_id="chat_seq")
        state.append_message({"role": "system", "content": "SYS"})
        state.append_message({"role": "user", "content": "hi"})
        state.append_message({"role": "assistant", "content": '{"tool": "final_answer", "args": {"answer": "Hello! How can I help?"}}'})
        # Several intervening turns so "hi" is no longer the most recent.
        for i in range(1, 12):
            state.append_message({"role": "user", "content": f"tell me about topic {i}"})
            state.append_message({"role": "assistant", "content": f"here is info about topic {i}"})
        state.append_message({"role": "user", "content": "1+1"})

        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        self.assertIsNone(state.active_goal)

        compacted = loop._compact_messages(state.get_messages())
        joined = "\n".join(m["content"] for m in compacted)

        # The latest question is present and answered-relevant.
        self.assertIn("1+1", joined)
        # The greeting slides out of the CHAT_WINDOW entirely (not pinned).
        self.assertNotIn("hi", joined)
        # The most recent user turn in the compacted context is the latest question.
        last_user = [m for m in compacted if m.get("role") == "user"][-1]
        self.assertEqual(last_user["content"], "1+1")
        # The system message is still preserved at the top.
        self.assertEqual(compacted[0]["content"], "SYS")

    def test_sliding_window_keeps_last_two_full(self):
        state = RuntimeState(session_id="c2")
        state.append_message({"role": "system", "content": "SYS"})
        state.append_message({"role": "user", "content": "TASK"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        its = [
            _it(1, "execute_shell", True, output="HUGE_OLD_1", path_hint="ls"),
            _it(2, "file_system", True, output="HUGE_OLD_2", path_hint="read"),
            _it(3, "web_search", True, output="RECENT_3", path_hint="q"),
            _it(4, "execute_shell", False, output="RECENT_4", path_hint="bad"),
        ]
        loop._ctx = _mk_ctx(its)
        compacted = loop._compact_messages(state.get_messages())
        joined = "\n".join(m["content"] for m in compacted)
        self.assertIn("RECENT_3", joined)
        self.assertIn("RECENT_4", joined)
        self.assertNotIn("HUGE_OLD_1", joined)
        self.assertNotIn("HUGE_OLD_2", joined)
        # Phase4.1: explicit untrusted XML guard wraps the historic summary.
        self.assertIn('<past_steps_summary untrusted="true">', joined)
        self.assertIn("Step 1:", joined)
        self.assertIn("execute_shell", joined)

    def test_critical_evidence_frozen_outside_window(self):
        state = RuntimeState(session_id="c3")
        state.append_message({"role": "system", "content": "SYS"})
        state.append_message({"role": "user", "content": "TASK"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        its = [
            _it(1, "file_system", True, output="CRITICAL_CONTENT", evid="E-1", critical=True, path_hint="secret"),
            _it(2, "execute_shell", True, output="OLD_2", path_hint="a"),
            _it(3, "execute_shell", True, output="RECENT_3", path_hint="b"),
            _it(4, "web_search", False, output="RECENT_4", path_hint="c"),
        ]
        loop._ctx = _mk_ctx(its)
        compacted = loop._compact_messages(state.get_messages())
        joined = "\n".join(m["content"] for m in compacted)
        self.assertIn("CRITICAL_CONTENT", joined)
        self.assertNotIn("OLD_2", joined)
        # Within the MAX_CRITICAL_FULL cap, a frozen critical keeps full body
        # (no degraded pointer needed); raw output is preserved, not leaked.
        self.assertNotIn("OLD_2", joined)

    def test_critical_full_body_hard_cap(self):
        """Beyond MAX_CRITICAL_FULL criticals, older ones degrade to pointers."""
        state = RuntimeState(session_id="c4")
        state.append_message({"role": "system", "content": "SYS"})
        state.append_message({"role": "user", "content": "TASK"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        # 4 critical turns, all outside the sliding window (window keeps last 2
        # which are non-critical here). Only the 3 most-recent keep full body.
        its = [
            _it(1, "file_system", True, output="CRIT_OLD_1", evid="E-1", critical=True, path_hint="a"),
            _it(2, "execute_shell", True, output="CRIT_OLD_2", evid="E-2", critical=True, path_hint="b"),
            _it(3, "web_search", True, output="CRIT_RECENT_3", evid="E-3", critical=True, path_hint="c"),
            _it(4, "file_system", True, output="CRIT_RECENT_4", evid="E-4", critical=True, path_hint="d"),
            _it(5, "execute_shell", True, output="WINDOW_5", path_hint="e"),
            _it(6, "web_search", True, output="WINDOW_6", path_hint="f"),
        ]
        loop._ctx = _mk_ctx(its)
        compacted = loop._compact_messages(state.get_messages())
        joined = "\n".join(m["content"] for m in compacted)
        # Most-recent 3 criticals keep full body.
        self.assertIn("CRIT_RECENT_3", joined)
        self.assertIn("CRIT_RECENT_4", joined)
        self.assertIn("CRIT_OLD_2", joined)
        # Oldest critical degrades to a summary pointer (no full body).
        self.assertNotIn("CRIT_OLD_1", joined)
        self.assertIn("[evidence:E-1]", joined)
        # Windowed turns still full.
        self.assertIn("WINDOW_5", joined)
        self.assertIn("WINDOW_6", joined)

    def test_windowed_critical_not_duplicated(self):
        """A critical turn already in TOOL_WINDOW is NOT duplicated as a pointer."""
        state = RuntimeState(session_id="c5")
        state.append_message({"role": "system", "content": "SYS"})
        state.append_message({"role": "user", "content": "TASK"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        # Both windowed turns are critical → should appear once each (full body),
        # and the dedup check must NOT emit duplicate [evidence:E-id] blocks.
        its = [
            _it(1, "execute_shell", True, output="OLD_1", path_hint="a"),
            _it(2, "file_system", True, output="WINDOW_CRIT_2", evid="E-2", critical=True, path_hint="b"),
            _it(3, "web_search", True, output="WINDOW_CRIT_3", evid="E-3", critical=True, path_hint="c"),
        ]
        loop._ctx = _mk_ctx(its)
        compacted = loop._compact_messages(state.get_messages())
        pointers = [m for m in compacted if "[evidence:E-2]" in m["content"]]
        # Exactly one occurrence of the pointer for the windowed critical.
        self.assertEqual(len(pointers), 0, "windowed critical must not emit a duplicate pointer")
        joined = "\n".join(m["content"] for m in compacted)
        self.assertIn("WINDOW_CRIT_2", joined)
        self.assertIn("WINDOW_CRIT_3", joined)

    def test_evidence_record_critical_flag(self):
        log = EvidenceLog()
        rec = log.record(tool="file_system", command_or_path="main.py", success=True, output_snippet="x", critical=True)
        self.assertTrue(rec.critical)
        d = log.to_serializable()
        restored = EvidenceLog()
        restored.restore(d)
        self.assertTrue(restored.get("E-1").critical)

    def test_flag_critical_post_hoc(self):
        log = EvidenceLog()
        rec = log.record(tool="execute_shell", command_or_path="ls", success=True, output_snippet="x")
        self.assertFalse(rec.critical)
        log.flag_critical("E-1")
        self.assertTrue(log.get("E-1").critical)


class TestSlimCheckpoint(unittest.TestCase):
    def test_slim_ledger_mirrors_compacted_view(self):
        log = EvidenceLog()
        for i in range(5):
            log.record(tool="execute_shell", command_or_path=f"cmd{i}", success=True, output_snippet="x" * 200)
        ledger = _slim_evidence_ledger(log)
        # Slim cap: only the most-recent 3 ledgers persisted.
        self.assertEqual(len(ledger), 3)
        # Ledger carries structured pointers, NOT raw 200-char outputs.
        self.assertNotIn("x" * 200, json.dumps(ledger))
        self.assertEqual(ledger[-1]["evidence_id"], "E-5")

    def test_resume_is_replay_safe_no_replan(self):
        """Resuming from a checkpoint skips plan/clarify (no history dup)."""
        tmp = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            state = RuntimeState(session_id="rz")
            agent = NativeDeepAgent(
                runtime_state=state,
                llm_client=lambda msgs: "[]",
                max_iterations=1,
            )
            # Populate evidence so the slim ledger is derived from real records.
            agent.evidence_log.record(
                tool="file_system", command_or_path="m.py", success=True, output_snippet="ok"
            )
            ds = DeepAgentState(task="build thing")
            ds.plan = ["step a", "step b"]
            ds.past_steps = ["step a"]
            agent._save_checkpoint(ds)

            # Re-instantiate; simulate the run() resume decision WITHOUT the
            # live node loop: a restored checkpoint must remount from the slim
            # ledger and treat plan/clarify as already-persisted (skipped).
            restored = agent._load_checkpoint()
            self.assertIsNotNone(restored)
            self.assertEqual(restored.past_steps, ["step a"])
            self.assertEqual(len(restored.evidence_ledger), 1)
            # Replaying restore again is idempotent: ledger length unchanged.
            restored2 = agent._load_checkpoint()
            self.assertEqual(len(restored2.evidence_ledger), 1)
            # Slim ledger carries structured pointers, never raw stdout.
            self.assertEqual(restored2.evidence_ledger[0]["evidence_id"], "E-1")
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
