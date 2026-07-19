"""Unit proof of the unified exploration contract (Phase 0, criteria 3 & 4).

Proves Guard 4 and the Structural Verifier agree, so no deadlock:
  - a single non-recursive `list .` is permitted (verifier needs directories>=1)
  - targeted file reads are always permitted
  - a recursive whole-tree scan is still blocked (the pathological loop)
  - a second root listing is blocked
  - with list . + >=3 file reads, check_investigation_gates PASSES
"""

import unittest
from unittest.mock import MagicMock

from engine.loop import ExecutionLoop, _LoopCtx
from engine.state import RuntimeState
from core.evidence import EvidenceRecord
from core.parser import ToolCall
from core.investigation import check_investigation_gates


def _tool(action, path, recursive="false"):
    return ToolCall(tool="file_system", args={"action": action, "path": path, "recursive": recursive})


class TestUnifiedExplorationContract(unittest.TestCase):
    def _loop(self):
        state = RuntimeState(session_id="test-unified-contract")
        loop = ExecutionLoop(state=state)
        loop._ctx = _LoopCtx(user_prompt="افحص بنية core")
        return loop

    def test_single_root_list_permitted(self):
        loop = self._loop()
        # First non-recursive root list → allowed (None = proceed to dispatch).
        self.assertIsNone(loop._pre_dispatch_guard(_tool("list", ".")))
        # But root_list_count is now 1, so a second root list is blocked.
        blocked = loop._pre_dispatch_guard(_tool("list", "."))
        self.assertIsNotNone(blocked)
        self.assertTrue(loop._force_final)

    def test_recursive_whole_tree_scan_blocked(self):
        loop = self._loop()
        blocked = loop._pre_dispatch_guard(_tool("list", ".", recursive="true"))
        self.assertIsNotNone(blocked)
        self.assertTrue(loop._force_final)

    def test_targeted_reads_always_permitted(self):
        loop = self._loop()
        for p in ("pyproject.toml", "main.py", "core/evidence.py"):
            self.assertIsNone(loop._pre_dispatch_guard(_tool("read", p)))

    def test_verifier_accepts_directed_exploration(self):
        # Simulate the evidence a directed exploration produces.
        records = [
            EvidenceRecord(evidence_id="E-1", tool="file_system", command_or_path=".",
                           action="list", output_snippet="core/  engine/  main.py  pyproject.toml", success=True),
            EvidenceRecord(evidence_id="E-2", tool="file_system", command_or_path="pyproject.toml",
                           action="read", output_snippet='name = "nabdcode"', success=True),
            EvidenceRecord(evidence_id="E-3", tool="file_system", command_or_path="main.py",
                           action="read", output_snippet="def main():\n    ...", success=True),
            EvidenceRecord(evidence_id="E-4", tool="file_system", command_or_path="core/evidence.py",
                           action="read", output_snippet="class EvidenceLog:", success=True),
        ]
        passed, details = check_investigation_gates("افحص بنية core", records)
        self.assertTrue(passed, f"Verifier rejected valid exploration: {details}")

    def test_listing_alone_rejected(self):
        """A bare directory listing (no reads) must NOT satisfy the verifier."""
        records = [
            EvidenceRecord(evidence_id="E-1", tool="file_system", command_or_path=".",
                           action="list", output_snippet="core/  engine/  main.py", success=True),
            EvidenceRecord(evidence_id="E-2", tool="file_system", command_or_path="core",
                           action="list", output_snippet="evidence.py  investigation.py", success=True),
            EvidenceRecord(evidence_id="E-3", tool="file_system", command_or_path="engine",
                           action="list", output_snippet="loop.py", success=True),
        ]
        passed, _ = check_investigation_gates("افحص بنية core", records)
        self.assertFalse(passed, "Verifier wrongly accepted listings with zero file reads")

    def test_echo_rejected(self):
        """A final answer that echoes tool output verbatim must be rejected."""
        from core.evidence import EvidenceLog
        log = EvidenceLog()
        log.record(tool="file_system", command_or_path="core", action="list",
                   success=True, output_snippet="evidence.py  investigation.py")
        log.record(tool="file_system", command_or_path="core/evidence.py", action="read",
                   success=True, output_snippet="class EvidenceLog:")
        echo_answer = "Based on the gathered evidence: [file_system] Directory listing for 'core' — 55 entries"
        with self.assertRaises(Exception):
            log.verify_fresh(require_tools=True, claim=echo_answer, user_prompt="افحص بنية core")
        # A real synthesis must pass (needs >=3 reads to satisfy the verifier).
        log.record(tool="file_system", command_or_path="pyproject.toml", action="read",
                   success=True, output_snippet='name = "nabdcode"')
        log.record(tool="file_system", command_or_path="main.py", action="read",
                   success=True, output_snippet="def main(): ...")
        good_answer = "## Core Architecture\nThe `core/` package defines `EvidenceLog` (see core/evidence.py) which stores tool outputs immutably. `pyproject.toml` names the project nabdcode; `main.py` is the entry point."
        # (no exception expected)
        log.verify_fresh(require_tools=True, claim=good_answer, user_prompt="افحص بنية core")

    def test_no_deadlock_contract(self):
        """The exact sequence the live run would emit must not trigger Guard 4
        AND must satisfy the verifier — proving the deadlock is gone."""
        loop = self._loop()
        seq = [
            _tool("list", "."),
            _tool("read", "pyproject.toml"),
            _tool("read", "main.py"),
            _tool("read", "core/evidence.py"),
        ]
        for tc in seq:
            self.assertIsNone(
                loop._pre_dispatch_guard(tc),
                f"Guard 4 wrongly blocked a directed-exploration call: {tc.args}",
            )
        # And the verifier would accept the resulting evidence.
        records = [
            EvidenceRecord(evidence_id="E-1", tool="file_system", command_or_path=".", action="list",
                           output_snippet="core/  engine/  main.py  pyproject.toml", success=True),
            EvidenceRecord(evidence_id="E-2", tool="file_system", command_or_path="pyproject.toml", action="read",
                           output_snippet='name = "nabdcode"', success=True),
            EvidenceRecord(evidence_id="E-3", tool="file_system", command_or_path="main.py", action="read",
                           output_snippet="def main():\n    ...", success=True),
            EvidenceRecord(evidence_id="E-4", tool="file_system", command_or_path="core/evidence.py", action="read",
                           output_snippet="class EvidenceLog:", success=True),
        ]
        passed, details = check_investigation_gates("افحص بنية core", records)
        self.assertTrue(passed, f"Deadlock: verifier rejects the only path Guard 4 permits: {details}")


if __name__ == "__main__":
    unittest.main()
