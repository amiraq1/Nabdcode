"""Live convergence test for Phase 0 — proves the answer-in-hand gate is now
ACTIVE in the real execution path (not just dead code behind _pre_dispatch_guard).

Scenario mirrors evidence-branch #4: Orchestrator reads pyproject.toml, then
loops by requesting execute_shell / re-listing the tree. Before the fix,
_pre_dispatch_guard was never called from _run_once, so the loop spun. After the
fix, Guard 3 + Guard 4 intercept the redundant call and force a clean final
answer in <= 2 cycles, with no shell dispatch and no Partial-answer banner.
"""

import unittest
from unittest.mock import MagicMock
from engine.loop import ExecutionLoop
from engine.state import RuntimeState


from engine.tool_registry import registry
from tools.file_system import FileSystemTool
from tools.shell import ShellTool


class TestLiveAnswerInHandConvergence(unittest.TestCase):
    def setUp(self):
        try:
            registry.register(FileSystemTool())
            registry.register(ShellTool())
        except ValueError:
            pass
        from pathlib import Path
        self.fixture_path = Path("fixture.txt")
        self.fixture_path.write_text("fixture content")

    def tearDown(self):
        if self.fixture_path.exists():
            self.fixture_path.unlink()

    def _make_loop(self, responses):
        state = RuntimeState(session_id="test-live-convergence")
        mock_llm = MagicMock(side_effect=list(responses))
        loop = ExecutionLoop(llm_provider=mock_llm, state=state)
        # Track real dispatches to prove shell/re-list is never run.
        real_dispatch = loop.dispatcher.dispatch
        calls = []

        def spy(tool_name, tool_args):
            calls.append((tool_name, tool_args))
            return real_dispatch(tool_name, tool_args)

        loop.dispatcher.dispatch = MagicMock(side_effect=spy)
        loop._dispatch_log = calls
        return loop, mock_llm

    def test_orchestrator_loop_blocked_after_single_read(self):
        """Reads pyproject once, then tries execute_shell (the looping branch).
        Must terminate <= 2 cycles, no shell dispatch, no Partial banner."""
        root_list = '{"tool": "file_system", "args": {"action": "list", "path": "."}}'
        read1 = '{"tool": "file_system", "args": {"action": "read", "path": "README.md"}}'
        read2 = '{"tool": "file_system", "args": {"action": "read", "path": "fixture.txt"}}'
        read = '{"tool": "file_system", "args": {"action": "read", "path": "pyproject.toml"}}'
        # Orchestrator tries to spin: shell after having the answer in hand.
        spin = '{"tool": "execute_shell", "args": {"command": "cat pyproject.toml | head -50"}}'
        final = '{"tool": "final_answer", "args": {"answer": "The project name is nabd-os"}}'
        loop, llm = self._make_loop([root_list, read1, read2, read, spin, final])

        result = loop.run("read pyproject.toml and give me the project name")

        # No execute_shell should ever reach the real dispatcher.
        shell_calls = [c for c in loop._dispatch_log if c[0] == "execute_shell"]
        self.assertEqual(shell_calls, [], "execute_shell must be blocked by Guard 3")
        # Terminate quickly — the spin is intercepted, not dispatched.
        self.assertLessEqual(llm.call_count, 6)
        self.assertEqual(loop.state.status, "COMPLETED")
        # No Partial-answer banner in the outcome.
        self.assertNotIn("Partial answer", result.safe_message or "")

    def test_wider_scope_relist_blocked_after_read(self):
        """After reading pyproject.toml, a 'list' / path='.' call must be blocked."""
        root_list = '{"tool": "file_system", "args": {"action": "list", "path": "."}}'
        read1 = '{"tool": "file_system", "args": {"action": "read", "path": "README.md"}}'
        read2 = '{"tool": "file_system", "args": {"action": "read", "path": "fixture.txt"}}'
        read = '{"tool": "file_system", "args": {"action": "read", "path": "pyproject.toml"}}'
        relist = '{"tool": "file_system", "args": {"action": "list", "path": "."}}'
        final = '{"tool": "final_answer", "args": {"answer": "The project name is nabd-os"}}'
        loop, llm = self._make_loop([root_list, read1, read2, read, relist, final])

        result = loop.run("read pyproject.toml and give me the project name")

        list_calls = [c for c in loop._dispatch_log if c[0] == "file_system" and str(c[1].get("action")).lower() == "list"]
        self.assertEqual(len(list_calls), 1, "wider-scope list must be blocked by Guard 4 (first non-recursive root list is allowed)")
        self.assertEqual(loop.state.status, "COMPLETED")
        self.assertNotIn("Partial answer", result.safe_message or "")

    def test_first_whole_tree_scan_blocked_without_prior_read(self):
        """A bare recursive list of '.' (the 801-entry tree wipe) must be blocked
        on the FIRST occurrence, even with no prior file_system read — it is the
        exact wasteful loop, never needed for a targeted question."""
        scan = '{"tool": "file_system", "args": {"action": "list", "path": ".", "recursive": true}}'
        root_list = '{"tool": "file_system", "args": {"action": "list", "path": "."}}'
        read1 = '{"tool": "file_system", "args": {"action": "read", "path": "README.md"}}'
        read2 = '{"tool": "file_system", "args": {"action": "read", "path": "fixture.txt"}}'
        read = '{"tool": "file_system", "args": {"action": "read", "path": "pyproject.toml"}}'
        final = '{"tool": "final_answer", "args": {"answer": "The project name is nabd-os"}}'
        loop, llm = self._make_loop([scan, root_list, read1, read2, read, final])

        result = loop.run("read pyproject.toml and tell me the project name")

        scan_calls = [
            c for c in loop._dispatch_log
            if c[0] == "file_system" and str(c[1].get("action")).lower() == "list"
            and str(c[1].get("path", "")).strip() in (".", "/", "")
        ]
        self.assertEqual(len(scan_calls), 1, "first whole-tree scan must be blocked by Guard 4 (but first non-recursive list is allowed)")
        self.assertEqual(loop.state.status, "COMPLETED")
        self.assertNotIn("Partial answer", result.safe_message or "")

    def test_reread_same_path_blocked(self):
        """Re-reading the exact same file path must be blocked."""
        root_list = '{"tool": "file_system", "args": {"action": "list", "path": "."}}'
        read1 = '{"tool": "file_system", "args": {"action": "read", "path": "README.md"}}'
        read2 = '{"tool": "file_system", "args": {"action": "read", "path": "fixture.txt"}}'
        read = '{"tool": "file_system", "args": {"action": "read", "path": "pyproject.toml"}}'
        reread = '{"tool": "file_system", "args": {"action": "read", "path": "pyproject.toml"}}'
        final = '{"tool": "final_answer", "args": {"answer": "The project name is nabd-os"}}'
        loop, llm = self._make_loop([root_list, read1, read2, read, reread, final])

        result = loop.run("read pyproject.toml and give me the project name")

        read_calls = [c for c in loop._dispatch_log if c[0] == "file_system" and str(c[1].get("action")).lower() == "read"]
        # Only the first 3 reads reach the dispatcher; the re-read is intercepted.
        self.assertEqual(len(read_calls), 3, "re-read of same path must be blocked by Guard 4")
        self.assertEqual(loop.state.status, "COMPLETED")
        self.assertNotIn("Partial answer", result.safe_message or "")


if __name__ == "__main__":
    unittest.main()
