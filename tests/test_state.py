# tests/test_state.py
import unittest
from engine.state import RuntimeState, _estimate_tokens, CHARS_PER_TOKEN


class TestRuntimeState(unittest.TestCase):
    def test_estimate_tokens_unified_heuristic(self):
        prose = "This is a regular English sentence explaining a design concept."
        code = "{'id': [1,2,3], 'fn': (a+b)*(c-d)/(e|f), 'meta': {'x': [!0, !1]}}"

        prose_tokens = _estimate_tokens(prose)
        code_tokens = _estimate_tokens(code)

        self.assertGreater(prose_tokens, 0)
        self.assertGreater(code_tokens, 0)
        # Phase4 unified ~4 chars/token estimate for both prose and code.
        expected_prose = max(1, int(len(prose) / CHARS_PER_TOKEN))
        expected_code = max(1, int(len(code) / CHARS_PER_TOKEN))
        self.assertEqual(prose_tokens, expected_prose)
        self.assertEqual(code_tokens, expected_code)

    def test_thread_safe_mutations(self):
        state = RuntimeState(session_id="test_sess")
        self.assertEqual(state.status, "INITIALIZED")
        state.update_status("RUNNING")
        self.assertEqual(state.status, "RUNNING")
        state.increment_step()
        self.assertEqual(state.step_count, 1)
        state.append_message({"role": "user", "content": "hello"})
        self.assertEqual(len(state.get_messages()), 1)
        self.assertEqual(state.get_last_message(), {"role": "user", "content": "hello"})

    def test_prune_history_preserves_system_and_user_task_with_active_goal(self):
        state = RuntimeState(session_id="prune_test", max_context_tokens=30)
        # System prompt at index 0 — always hard-preserved.
        state.append_message({"role": "system", "content": "SYS"})  # ~1 token
        # Original user task at index 1 — hard-preserved WHEN a goal is active.
        state.append_message({"role": "user", "content": "TASK"})  # ~1 token
        from engine.state import GoalSpec
        state.active_goal = GoalSpec(raw_prompt="TASK", success_criteria="task done")
        # Add old messages that exceed 30 tokens total.
        for i in range(1, 7):
            state.append_message({
                "role": "user",
                "content": f"Message number {i} with a decent length text string to fill tokens."
            })

        state.prune_history()
        messages = state.get_messages()
        # System prompt must remain at index 0.
        self.assertEqual(messages[0]["content"], "SYS")
        # Original user task must remain at index 1 (frozen by active goal).
        self.assertEqual(messages[1]["content"], "TASK")
        # Final set must fit the budget (<= 30 tokens).
        total = sum(_estimate_tokens(m.get("content", "")) for m in messages)
        self.assertLessEqual(total, 30)

    def test_prune_history_drops_user_task_in_casual_chat(self):
        """Without an active goal, messages[1] competes in the window and can
        slide out under token pressure (no greeting-loop pin)."""
        state = RuntimeState(session_id="prune_casual", max_context_tokens=30)
        state.append_message({"role": "system", "content": "SYS"})  # ~1 token
        state.append_message({"role": "user", "content": "hi"})  # stale greeting
        # Many newer, larger messages that blow the 30-token budget.
        for i in range(1, 8):
            state.append_message({
                "role": "user",
                "content": f"Message number {i} with a decent length text string to fill tokens."
            })
        self.assertIsNone(state.active_goal)

        state.prune_history()
        messages = state.get_messages()
        # System prompt always preserved.
        self.assertEqual(messages[0]["content"], "SYS")
        # The stale greeting is NOT pinned — it may be among the dropped turns.
        self.assertNotEqual(messages[1]["content"], "hi")
        # Budget respected.
        total = sum(_estimate_tokens(m.get("content", "")) for m in messages)
        self.assertLessEqual(total, 30)

    def test_loop_safe_guard(self):
        state = RuntimeState(session_id="loop_guard", max_steps=3)
        self.assertTrue(state.is_loop_safe())
        state.increment_step()
        state.increment_step()
        state.increment_step()
        self.assertFalse(state.is_loop_safe())

    def test_clear_context(self):
        state = RuntimeState(session_id="clear_test")
        state.append_message({"role": "system", "content": "SYS"})
        state.append_message({"role": "user", "content": "hello"})
        state.increment_step()
        state.past_steps_summary = "Old steps"
        state.compacted_memory.append("Old mem")
        state.tool_interactions.append("Old tool")
        from engine.state import GoalSpec
        state.active_goal = GoalSpec(raw_prompt="Goal", success_criteria="Done")

        state.clear_context()
        self.assertEqual(len(state.get_messages()), 1)
        self.assertEqual(state.get_messages()[0]["content"], "SYS")
        self.assertEqual(state.step_count, 0)
        self.assertEqual(state.past_steps_summary, "")
        self.assertEqual(len(state.compacted_memory), 0)
        self.assertEqual(len(state.tool_interactions), 0)
        self.assertIsNone(state.active_goal)

    def test_evidence_and_todo_clear(self):
        from core.evidence import EvidenceLog
        from core.todo import TodoManager
        elog = EvidenceLog()
        elog.record("test_tool", "cmd", True, "snippet")
        self.assertTrue(elog.has_evidence())
        elog.clear()
        self.assertFalse(elog.has_evidence())

        tman = TodoManager()
        tman.set_plan(["Task 1"])
        self.assertEqual(len(tman.all()), 1)
        tman.clear()
        self.assertEqual(len(tman.all()), 0)


if __name__ == "__main__":
    unittest.main()
