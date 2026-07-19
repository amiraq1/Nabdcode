"""Automated verification suite ensuring TODO_DISCIPLINE is injected into the system prompt."""

import unittest
from pathlib import Path
import pytest
from core.constants import TODO_DISCIPLINE
from engine.loop import ExecutionLoop
from engine.state import RuntimeState


@pytest.fixture(autouse=True)
def graphify_graph(tmp_path, monkeypatch):
    """Simulate an active graphify workspace by creating graph.json.

    The injection gate (beb116a) only injects GRAPHIFY_KNOWLEDGE_GRAPH_POLICY
    when graphify-out/graph.json exists, so the test must provide one.
    Redirect get_workspace_root() to the temp dir used by the gate.
    """
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    (graph_dir / "graph.json").write_text('{"nodes": [], "edges": []}')
    monkeypatch.setattr(
        "core.kernel.security.get_workspace_root",
        lambda: str(tmp_path),
    )


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

    def test_python_and_code_exploration_policy_injected(self):
        from core.constants import PYTHON_AND_CODE_EXPLORATION_POLICY
        state = RuntimeState(session_id="test_python_policy")
        state.append_message({"role": "user", "content": "Calculate the sum of primes"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        messages = loop._inject_runtime_context([{"role": "user", "content": "Calculate the sum of primes"}])
        system_content = messages[0]["content"]
        self.assertIn("Python Execution & Code Intelligence Policy", system_content)
        self.assertIn("python_repl", system_content)
        self.assertIn("code_intelligence", system_content)

    def test_taste_profile_injected(self):
        state = RuntimeState(session_id="test_taste_injection")
        state.append_message({"role": "user", "content": "Write some clean code"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        messages = loop._inject_runtime_context([{"role": "user", "content": "Write some clean code"}])
        system_content = messages[0]["content"]
        self.assertIn("Developer Taste Profile (Mandatory Rules)", system_content)
        self.assertIn("Prefer zero-dependency solutions when possible.", system_content)

    def test_graphify_policy_injected(self):
        state = RuntimeState(session_id="test_graphify_injection")
        state.append_message({"role": "user", "content": "Explain structure"})
        loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
        messages = loop._inject_runtime_context([{"role": "user", "content": "Explain structure"}])
        system_content = messages[0]["content"]
        self.assertIn("Graphify Knowledge Graph Policy (Mandatory)", system_content)
        self.assertIn("graphify_tool", system_content)


if __name__ == "__main__":
    unittest.main()
