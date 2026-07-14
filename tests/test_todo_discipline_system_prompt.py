"""Automated verification suite ensuring TODO_DISCIPLINE is injected into the system prompt."""

import unittest
from core.constants import TODO_DISCIPLINE
from engine.loop import ExecutionLoop
from engine.state import RuntimeState


class TestTodoDisciplineInjected(unittest.TestCase):
    def test_todo_discipline_injected_in_loop(self):
        state = RuntimeState(session_id="test_discipline")
        state.append_message({"role": "system", "content": "Base System Prompt"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")

        compacted = loop._compact_messages(state.get_messages())
        from core.constants import TODO_DISCIPLINE
        prefix = f"{TODO_DISCIPLINE}\n\n"
        full_system_content = prefix + compacted[0]["content"]

        self.assertIn("TODO Discipline (Mandatory)", full_system_content)
        self.assertIn("todo_write", full_system_content)

    def test_security_compliance_rule_injected(self):
        from core.constants import SECURITY_COMPLIANCE_RULE
        from pathlib import Path
        self.assertIn("SECURITY COMPLIANCE RULE", SECURITY_COMPLIANCE_RULE)
        self.assertIn("restricted by the secure execution policy", SECURITY_COMPLIANCE_RULE)
        agent_md = Path("AGENT.md").read_text(encoding="utf-8")
        self.assertIn("SECURITY COMPLIANCE RULE", agent_md)

    def test_language_policy_injected(self):
        from core.constants import LANGUAGE_POLICY
        from pathlib import Path
        self.assertIn("Language & Communication Policy", LANGUAGE_POLICY)
        self.assertIn("exclusively in fluent, professional English", LANGUAGE_POLICY)
        agent_md = Path("AGENT.md").read_text(encoding="utf-8")
        self.assertIn("Language & Communication Policy", agent_md)


if __name__ == "__main__":
    unittest.main()
