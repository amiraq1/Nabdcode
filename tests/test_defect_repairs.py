"""Regression tests for the D-series defect repairs (FORENSIC_DEFECT_LEDGER).

Each test names the defect it pins; every test fails on the pre-repair code:

- D-01  edit rejection crashed with ToolResult(output=...) TypeError
- D-02  read_many crashed with ToolResult(summary=...) TypeError
- D-03  task tool success path crashed with ToolResult(output=...) TypeError
- D-04  piped commands silently mangled (missing subprocess import swallowed)
- D-05  background execution dead (same missing import)
- D-07  dead "authoritative" goal gate (wrong-module import, swallowed)
- D-08  _dispatch_and_record_evidence shadowed → WRONG_TOOL path unreachable
- D-09  default_guard NameErrors (uv isolation + DAG terminal node)
- D-10  OpenRouterClient.stream() was not a generator
- D-11  DAG executor had no path jail (fixed @6346a22 — pinned here)
- D-12  accept-edits gate bound by value → never opened after set_mode()

Bonus latent crash found while repairing D-07: goal_verifier.evaluate_goal_exit
crashed with AttributeError for goals without success_criteria (Optional field).
"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestD01EditRejectionNoCrash(unittest.TestCase):
    """D-01: rejecting an edit (or gate timeout) must return cleanly."""

    def test_rejection_returns_clean_result_not_typeerror(self):
        from engine._dispatch import _ToolDispatchMixin
        from core.evidence import EvidenceLog
        from core.kernel.state import RuntimeState

        class _Dummy(_ToolDispatchMixin):
            POLL_DELAY = 0

            def __init__(self):
                self.evidence_log = EvidenceLog()
                self.state = RuntimeState(session_id="t")
                self.max_output_len = 2000
                self._ctx = None

            def _build_tool_feedback(self, result, tool_name, tool_args, output):
                return output

        class _RejectingBridge:
            def emit(self, name, **kwargs):
                if name == "edit_proposed":
                    kwargs["decision_box"]["approved"] = False
                    kwargs["event"].set()

        import engine._dispatch as dispatch_mod

        dummy = _Dummy()
        with patch.object(dispatch_mod, "get_bridge", return_value=_RejectingBridge()):
            handled = dummy._handle_consent_and_edit_gate(
                "file_system", {"action": "edit", "path": "a.py", "content": "x"}
            )
        self.assertTrue(handled)
        msgs = dummy.state.get_messages()
        self.assertTrue(
            any("REJECTED THE EDIT" in str(m.get("content", "")) for m in msgs),
            f"expected rejection feedback in messages, got: {msgs!r}",
        )


class TestD02ReadMany(unittest.TestCase):
    """D-02: read_many must return a valid ToolResult."""

    def test_read_many_returns_combined_content(self):
        from tools.file_system import FileSystemTool

        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.txt").write_text("AAA", encoding="utf-8")
            Path(td, "b.txt").write_text("BBB", encoding="utf-8")
            tool = FileSystemTool(workspace=td)
            res = tool.execute(action="read_many", path=".", paths=["a.txt", "b.txt"])
        self.assertTrue(res.success, res.stderr)
        self.assertIn("AAA", res.stdout)
        self.assertIn("BBB", res.stdout)
        self.assertIn("summary", res.metadata)


class TestD03TaskToolSuccess(unittest.TestCase):
    """D-03: a successful sub-agent run must construct its ToolResult."""

    def test_execute_success_path(self):
        from tools.task_tool import TaskTool
        import engine.subagent_runner as sr

        orig_run = sr.SubagentRunner.run
        orig_cheap = TaskTool._cheap_provider
        sr.SubagentRunner.run = lambda self, prompt: {
            "result": "sub ok",
            "evidence": ["E-1"],
            "files_read": ["a.py"],
            "tool_calls": 1,
        }
        TaskTool._cheap_provider = lambda self, model: (lambda *a, **k: "x")
        try:
            res = TaskTool().execute("do it")
        finally:
            sr.SubagentRunner.run = orig_run
            TaskTool._cheap_provider = orig_cheap
        self.assertTrue(res.success, res.stderr)
        self.assertIn('"result": "sub ok"', res.stdout)
        self.assertIn("E-1", res.stdout)


class TestD04D05PipesAndBackground(unittest.TestCase):
    """D-04/D-05: pipelines execute as pipelines; background launch works."""

    def test_pipe_executes_pipeline_semantics(self):
        from core.utils import safe_execute_command

        rc, out, err = safe_execute_command("echo hello | wc -l")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "1")

    def test_multi_segment_pipeline(self):
        from core.utils import safe_execute_command

        rc, out, err = safe_execute_command("echo x | grep x | wc -l")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "1")

    def test_failed_pipeline_not_reexecuted_as_simple(self):
        """Pre-repair, a pipe was silently re-run as a simple command whose
        stdout contained the literal '| wc -l' text. grep rc=1 is decisive."""
        from core.utils import safe_execute_command

        rc, out, err = safe_execute_command("echo hello | grep NOMATCH")
        self.assertEqual(rc, 1)
        self.assertNotIn("|", out)

    def test_blocked_pipeline_command_fails_closed(self):
        from core.utils import safe_execute_command

        rc, out, err = safe_execute_command("ls | rm -rf /tmp/x")
        self.assertEqual(rc, -1)
        self.assertIn("Security", err)

    def test_background_launch(self):
        from core.utils import safe_execute_command

        rc, out, err = safe_execute_command("echo bg > /dev/null &")
        self.assertEqual(rc, 0, err)
        self.assertIn("PID:", out)


class TestD07GoalGate(unittest.TestCase):
    """D-07: the goal branch must reach the real engine.goal_verifier."""

    def test_goal_branch_met_via_real_evaluator(self):
        from core.kernel.state import RuntimeState, GoalSpec
        from core.evidence import EvidenceLog
        from engine.loop import ExecutionLoop
        from engine._loop_types import _LoopCtx

        state = RuntimeState(session_id="t")
        state.active_goal = GoalSpec(
            raw_prompt="inspect pyproject.toml",
            success_criteria="pyproject.toml read",
        )
        el = EvidenceLog()
        loop = ExecutionLoop(state=state, llm_provider=lambda *a, **k: "x", evidence_log=el)
        loop._ctx = _LoopCtx(user_prompt="inspect pyproject.toml")
        el.record(
            tool="file_system",
            command_or_path="pyproject.toml",
            success=True,
            output_snippet="pyproject.toml content: [project] nabdcode",
        )
        self.assertTrue(loop._is_answer_in_hand_or_goal_met())
        self.assertTrue(loop._goal.is_met)

    def test_goal_verifier_tolerates_none_success_criteria(self):
        """Latent crash exposed by the D-07 repair: success_criteria is Optional."""
        from core.evidence import EvidenceLog
        from engine.state import GoalSpec
        from engine.goal_verifier import evaluate_goal_exit

        res = evaluate_goal_exit(GoalSpec(raw_prompt="anything"), EvidenceLog(), require_tools=True)
        self.assertFalse(res.ok)  # fail-closed on absent evidence — but must NOT raise


class TestD08DispatchResolution(unittest.TestCase):
    """D-08: the mixin's orchestrator (with WRONG_TOOL re-selection) binds."""

    def test_dispatch_orchestrator_comes_from_mixin(self):
        from engine.loop import ExecutionLoop
        from engine._dispatch import _ToolDispatchMixin

        self.assertIs(
            ExecutionLoop._dispatch_and_record_evidence,
            _ToolDispatchMixin._dispatch_and_record_evidence,
        )


class TestD09GuardImports(unittest.TestCase):
    """D-09: default_guard must be importable/invoked in both call sites."""

    def test_uv_manager_reaches_guard(self):
        import core.uv_isolation_manager as uv_mod

        mgr = uv_mod.UvIsolationManager(uv_bin="python3")
        with patch(
            "core.kernel.subprocess_guard.SubprocessGuard.run_infra",
            return_value=(0, "ok", ""),
        ) as mock_infra:
            out = mgr.run_in_isolated_env("print(1)", [])
        self.assertTrue(mock_infra.called)
        self.assertTrue(out["success"], out["stderr"])

    def test_dag_terminal_node_executes(self):
        from core.dag.nodes.terminal import TerminalNode
        from core.dag.context import NabdExecutionContext

        ctx = NabdExecutionContext(
            workspace_dir=".", shared_memory={"pending_command": "echo dag_ok"}
        )
        # S-2-FINAL: بلا تماس → fail-closed (حجب). نمرر تماسًا موافقًا كما
        # يفعله الإنتاج الآن (main.py يُكيِّف ConsentManager إلى bool) —
        # يبقى هذا العقد يختبر مسار التنفيذ الفعلي الذي كان D-09 يثبته.
        node = TerminalNode(consent_callback=lambda tool_name, args: True)
        edge = node.execute(ctx)
        self.assertEqual(edge.target_node_id, "end")
        self.assertIn("dag_ok", ctx.shared_memory.get("terminal_output", ""))


class TestD10StreamIsGenerator(unittest.TestCase):
    """D-10: stream() must yield delta dicts token-by-token."""

    def test_stream_is_generator_function(self):
        from core.llm import OpenRouterClient

        self.assertTrue(inspect.isgeneratorfunction(OpenRouterClient.stream))

    def test_stream_yields_delta_dicts(self):
        from core.llm import OpenRouterClient

        payload = (
            b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
            b"data: [DONE]\n"
        )

        class _FakeResp:
            def __init__(self, data):
                self._data, self._pos = data, 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, size=4096):
                chunk = self._data[self._pos : self._pos + size]
                self._pos += len(chunk)
                return chunk

            def close(self):
                pass

        client = OpenRouterClient(api_key="test")
        with patch("urllib.request.urlopen", return_value=_FakeResp(payload)):
            deltas = list(client.stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(deltas, [{"content": "Hel"}, {"content": "lo"}])


class TestD11ExecutorJail(unittest.TestCase):
    """D-11: DAG executor must refuse traversal/absolute write paths."""

    def test_traversal_key_rejected_and_nothing_written(self):
        from core.dag.nodes.executor import ExecutorNode
        from core.dag.context import NabdExecutionContext

        with tempfile.TemporaryDirectory() as td:
            ctx = NabdExecutionContext(
                workspace_dir=td, code_diffs={"../escape_probe.py": "x = 1"}
            )
            edge = ExecutorNode().execute(ctx)
            self.assertTrue(ctx.error_flags)
            self.assertEqual(edge.target_node_id, "end")
            self.assertFalse(Path(td).parent.joinpath("escape_probe.py").exists())


class TestD12AcceptEditsGateOpens(unittest.TestCase):
    """D-12: after set_mode(True), the propose gate must actually open."""

    def test_set_mode_true_opens_gate(self):
        from core import accept_edits_state as aes
        from tools.file_system import FileSystemTool

        with tempfile.TemporaryDirectory() as td:
            target = Path(td, "e.py")
            target.write_text("old\n", encoding="utf-8")
            aes.reset_session()
            aes.set_mode(True)
            try:
                tool = FileSystemTool(workspace=td)
                res = tool.execute(action="edit", path="e.py", content="new\n")
                self.assertTrue(res.success, res.stderr)
                pending = aes.peek_pending()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].path, "e.py")
                # queued for approval — NOT written yet
                self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            finally:
                aes.set_mode(False)
                aes.reset_session()


if __name__ == "__main__":
    unittest.main()
