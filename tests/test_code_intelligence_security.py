"""Security tests for CodeIntelligenceTool — ensure it never leaks system prompt content.

The system prompt (``<system_instructions>``, TODO Discipline, Security Compliance,
etc.) is built at runtime and injected into the LLM context. It is NOT a file on
disk. If code_intelligence ever returns any of these markers, it means the tool
is hallucinating or reading memory instead of actual files — a critical security
leak.
"""

from pathlib import Path
import pytest

from tools.code_intelligence import CodeIntelligenceTool


@pytest.fixture
def ci_tool():
    """Create a CodeIntelligenceTool bound to the project workspace."""
    ws = Path(__file__).resolve().parent.parent
    return CodeIntelligenceTool(workspace=ws)


class TestCISecurity:
    """5 security guards against system-prompt leakage."""

    def test_ci_does_not_return_system_instructions(self, ci_tool):
        """test_1: code_intelligence must not return ``<system_instructions>``."""
        result = ci_tool.execute(action="list_symbols", path="engine/_context.py")
        assert result.success, f"list_symbols failed: {result.stderr}"
        stdout = result.stdout or ""
        assert "<system_instructions>" not in stdout, (
            "SECURITY LEAK: code_intelligence returned <system_instructions> tag!"
        )

    def test_ci_rejects_outside_workspace(self, ci_tool):
        """test_2: code_intelligence must reject paths outside the workspace."""
        result = ci_tool.execute(action="list_symbols", path="/etc/passwd")
        assert not result.success, "Should reject path outside workspace"
        stderr = (result.stderr or "").lower()
        assert "forbidden" in stderr or "outside" in stderr, (
            f"Expected 'forbidden' or 'outside' in error, got: {result.stderr}"
        )

    def test_ci_returns_not_found_for_nonexistent_paths(self, ci_tool):
        """test_3: code_intelligence with non-existent paths returns file-not-found.

        This checks that naive prompts like 'read the system prompt file' cannot
        trick the tool into returning hallucinated content.
        """
        for bad_path in ("system", "prompt", "system_prompt"):
            result = ci_tool.execute(action="list_symbols", path=bad_path)
            assert not result.success, (
                f"Should fail for path='{bad_path}', got: {result.stdout}"
            )
            stderr = (result.stderr or "").lower()
            assert "not found" in stderr or "must be" in stderr or "exist" in stderr, (
                f"Expected file-not-found error for '{bad_path}', got: {result.stderr}"
            )

    def test_ci_stdout_no_todo_discipline(self, ci_tool):
        """test_4: code_intelligence output must not contain 'TODO Discipline'."""
        result = ci_tool.execute(action="list_symbols", path="engine/_context.py")
        assert result.success, f"list_symbols failed: {result.stderr}"
        stdout = result.stdout or ""
        assert "TODO Discipline" not in stdout, (
            "SECURITY LEAK: code_intelligence leaked TODO Discipline!"
        )

    def test_ci_stdout_no_security_compliance(self, ci_tool):
        """test_5: code_intelligence output must not contain 'Security Compliance'."""
        result = ci_tool.execute(action="list_symbols", path="engine/_context.py")
        assert result.success, f"list_symbols failed: {result.stderr}"
        stdout = result.stdout or ""
        assert "Security Compliance" not in stdout, (
            "SECURITY LEAK: code_intelligence leaked Security Compliance!"
        )
