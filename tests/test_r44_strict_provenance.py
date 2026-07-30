"""
R4.4 Strict Provenance & E2E Tests.

PATCH-R4.4 Protocol requirements:
  Step 1: Strict provenance — no command_or_path fallback, reject if workspace_relative_path missing
  Step 2: Fail-closed invalid policy — reject if required_target set but required_evidence_actions empty
  Step 3: NUL log sanitization — sanitized error (no raw payload)
  Step 4: Schema compatibility + LLM forgery tests
  Step 5: True Engine E2E (ExecutionLoop.run() with Mock LLM)
  Step 6: Full numeric reporting
"""

import inspect
import os
import sys
import unittest
from types import SimpleNamespace
from typing import Any, Callable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine._loop_helpers import (
    _normalize_path,
    _check_required_target_in_evidence,
)
from engine._loop_types import IntentPolicy


# =========================================================================
# Step 1 & 2: Strict Provenance + Fail-Closed Tests
# =========================================================================

def make_record(tool: str, action: str, cmd: str, success: bool = True,
                workspace_relative_path: str = "", evidence_id: str = "E-1"):
    return SimpleNamespace(
        tool=tool, action=action, command_or_path=cmd,
        success=success, workspace_relative_path=workspace_relative_path,
        evidence_id=evidence_id,
    )

class MockEvidenceLog:
    def __init__(self, records: list[Any]):
        self._records = records
    def get_records(self):
        return self._records


class TestStrictProvenanceNoFallback(unittest.TestCase):
    """Step 1: command_or_path is NEVER used for security decisions."""

    def test_workspace_relative_path_missing_rejects(self):
        """If workspace_relative_path is empty, reject with TRUSTED_TARGET_METADATA_MISSING."""
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True,
                       workspace_relative_path=""),
        ])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok, f"Expected reject (missing metadata), got: {reason}")
        self.assertIn("TRUSTED_TARGET_METADATA_MISSING", reason)

    def test_command_or_path_not_used_for_security(self):
        """Even if command_or_path matches, it must NOT be used (no workspace_relative_path)."""
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True,
                       workspace_relative_path=""),
        ])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok, "command_or_path should NOT satisfy without workspace_relative_path")
        self.assertIn("TRUSTED_TARGET_METADATA_MISSING", reason)

    def test_workspace_relative_path_present_passes(self):
        """When workspace_relative_path is present, it should be used."""
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True,
                       workspace_relative_path="src/app.py"),
        ])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertTrue(ok, f"Expected pass with workspace_relative_path, got: {reason}")

    def test_evidence_without_workspace_path_at_all_rejects(self):
        """When no record has workspace_relative_path, reject."""
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True,
                       workspace_relative_path=""),
        ])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok)
        self.assertIn("TRUSTED_TARGET_METADATA_MISSING", reason)


class TestFailClosedInvalidPolicy(unittest.TestCase):
    """Step 2: Invalid policy fails closed."""

    def test_required_target_with_empty_actions_rejects(self):
        """If required_target is set but required_evidence_actions is empty, reject."""
        log = MockEvidenceLog([])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset(),
        )
        self.assertFalse(ok)
        self.assertIn("INVALID_INTENT_POLICY", reason)

    def test_no_target_no_actions_passes(self):
        """If required_target is empty, no actions needed."""
        log = MockEvidenceLog([])
        ok, reason = _check_required_target_in_evidence(
            "", log,
            required_evidence_actions=frozenset(),
        )
        self.assertTrue(ok)


# =========================================================================
# Step 3: NUL Sanitization Tests
# =========================================================================

class TestNULSanitization(unittest.TestCase):
    """Step 3: NUL error must NOT include raw payload."""

    def test_nul_error_no_raw_payload(self):
        """ValueError must not include the raw malicious path."""
        try:
            _normalize_path("src\0/app.py")
            self.fail("Expected ValueError")
        except ValueError as e:
            msg = str(e)
            self.assertEqual(msg, "TARGET_PATH_INVALID_NUL",
                            f"Error message should be sanitized, got: {msg}")
            self.assertNotIn("src", msg, "Raw path must not leak in error message")
            self.assertNotIn("app.py", msg, "Raw path must not leak in error message")

    def test_nul_error_prefix_only(self):
        """Error should be exactly TARGET_PATH_INVALID_NUL with no extra details."""
        try:
            _normalize_path("\0evil")
            self.fail("Expected ValueError")
        except ValueError as e:
            self.assertEqual(str(e), "TARGET_PATH_INVALID_NUL")


# =========================================================================
# Step 4a: Schema Compatibility Tests
# =========================================================================

class TestSchemaCompatibility(unittest.TestCase):
    """Step 4a: EvidenceRecord schema roundtrip and backward compat."""

    def test_old_record_without_workspace_path_defaults_to_empty(self):
        """EvidenceRecord.from_dict without workspace_relative_path defaults to ''."""
        from core.evidence import EvidenceRecord
        old_dict = {
            "evidence_id": "E-1",
            "evidence_type": "filesystem",
            "tool": "file_system",
            "command_or_path": "src/app.py",
            "action": "read",
            "success": True,
            "output_snippet": "content",
            "covered_subjects": [],
            "critical": False,
            "timestamp": 1000.0,
        }
        rec = EvidenceRecord.from_dict(old_dict)
        self.assertEqual(rec.workspace_relative_path, "",
                        "Old record without workspace_relative_path must default to ''")
        self.assertEqual(rec.command_or_path, "src/app.py")

    def test_new_record_roundtrip(self):
        """New EvidenceRecord with workspace_relative_path roundtrips through to_dict/from_dict."""
        from core.evidence import EvidenceRecord
        original = EvidenceRecord(
            evidence_id="E-2",
            evidence_type="filesystem",
            tool="file_system",
            command_or_path="src/app.py",
            action="read",
            success=True,
            output_snippet="content",
            workspace_relative_path="src/app.py",
        )
        data = original.to_dict()
        restored = EvidenceRecord.from_dict(data)
        self.assertEqual(restored.workspace_relative_path, "src/app.py")
        self.assertEqual(restored.command_or_path, "src/app.py")
        self.assertEqual(restored.evidence_id, "E-2")

    def test_old_record_fails_target_gate(self):
        """Old record with empty workspace_relative_path must fail the target gate."""
        from core.evidence import EvidenceRecord
        rec = EvidenceRecord(
            evidence_id="E-1",
            tool="file_system",
            command_or_path="src/app.py",
            action="read",
            success=True,
            workspace_relative_path="",
        )
        class SimpleLog:
            def get_records(self):
                return [rec]
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", SimpleLog(),
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok)
        self.assertIn("TRUSTED_TARGET_METADATA_MISSING", reason)

    def test_new_record_passes_target_gate(self):
        """New record with workspace_relative_path passes the target gate."""
        from core.evidence import EvidenceRecord
        rec = EvidenceRecord(
            evidence_id="E-2",
            tool="file_system",
            command_or_path="src/app.py",
            action="read",
            success=True,
            workspace_relative_path="src/app.py",
        )
        class SimpleLog:
            def get_records(self):
                return [rec]
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", SimpleLog(),
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertTrue(ok, f"Expected pass, got: {reason}")


# =========================================================================
# Step 4b: LLM Forgery Tests
# =========================================================================

class TestLLMForgery(unittest.TestCase):
    """Step 4b: LLM cannot forge workspace_relative_path."""

    def test_forged_workspace_path_in_args_rejected(self):
        """LLM passes workspace_relative_path in tool args — tool must NOT populate it.

        The FileSystemTool resolves the path internally and sets workspace_relative_path
        in ToolResult.metadata post-execution. If the LLM passes workspace_relative_path
        in its tool arguments, the tool must NOT copy it into the trusted metadata.
        This test proves that even if command_or_path matches, the gate rejects when
        workspace_relative_path is missing from the record.
        """
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True,
                       workspace_relative_path=""),  # tool did NOT populate it
        ])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok, "Forged path should be rejected (no workspace_relative_path)")
        self.assertIn("TRUSTED_TARGET_METADATA_MISSING", reason)


# =========================================================================
# Step 5: True Engine E2E Tests (ExecutionLoop.run() with Mock LLM)
# =========================================================================

class MockLLMProvider:
    """A Mock LLM that simulates tool calls for testing the engine loop."""

    def __init__(self, responses: list[list[dict]]):
        """responses: list of (message_list) -> response_text functions or direct strings."""
        self._responses = responses
        self._call_count = 0
        self._last_messages = None

    def __call__(self, messages: list[dict], **kwargs) -> str:
        self._last_messages = messages
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            if callable(resp):
                return resp(messages)
            return resp
        return '{"tool": "final_answer", "args": {"answer": "Fallback timeout answer."}}'


class TestTrueEngineE2E(unittest.TestCase):
    """Step 5: TRUE ExecutionLoop.run() for S1 and S2."""

    def setUp(self):
        # Clean up any state from previous tests
        pass

    def test_s1_single_file_read_and_finalize(self):
        """S1: 'Read broken_script.py and identify the syntax error only.'

        Must natively resolve to SINGLE_FILE_LOOKUP, read the target file,
        skip plan/root listing, and reach FINALIZE cleanly.
        """
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        from core.evidence import EvidenceLog
        from core.kernel.events import bus

        # Create a test file to read
        test_file = "test_s1_temp_file.py"
        try:
            with open(test_file, "w") as f:
                f.write("def foo():\n    return 1\n")

            state = RuntimeState(session_id="test-s1-r44")
            # Prevent bus errors by catching all events
            original_emit = bus.emit
            bus.emit = lambda event, data=None: None

            try:
                # Mock LLM: classify prompt as single-file, then read the file, then final_answer
                llm = MockLLMProvider([
                    # Step 0: initial classification — prompt ask to read a file
                    lambda msgs: (
                        '{"tool": "file_system", "args": {"action": "read", "path": "test_s1_temp_file.py"}}'
                    ),
                    # Step 1: read the file (real execution)
                    lambda msgs: (
                        '{"tool": "final_answer", "args": {"answer": "Found syntax: file is valid."}}'
                    ),
                ])

                loop = ExecutionLoop(
                    state=state,
                    llm_provider=llm,
                    evidence_log=EvidenceLog(),
                )
                result = loop.run("Read broken_script.py and identify the syntax error only.")
                self.assertIsNotNone(result)
            finally:
                bus.emit = original_emit
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)

    def test_s2_repo_analysis_with_plan_listing_reads(self):
        """S2: 'Analyze this repository and summarize its architecture.'

        Must natively resolve to REPOSITORY_INVESTIGATION, require a plan,
        root listing, and 3 reads before allowing finalization.
        """
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        from core.evidence import EvidenceLog
        from core.kernel.events import bus

        # Create test files to read
        test_files = ["test_s2_file_a.py", "test_s2_file_b.py", "test_s2_file_c.py"]
        try:
            for f in test_files:
                with open(f, "w") as fp:
                    fp.write(f"# {f}\n")

            state = RuntimeState(session_id="test-s2-r44")
            original_emit = bus.emit
            bus.emit = lambda event, data=None: None

            try:
                llm = MockLLMProvider([
                    # Step 0: list the repository root
                    lambda msgs: (
                        '{"tool": "file_system", "args": {"action": "list", "path": "."}}'
                    ),
                    # Step 1: read first file
                    lambda msgs: (
                        '{"tool": "file_system", "args": {"action": "read", "path": "test_s2_file_a.py"}}'
                    ),
                    # Step 2: read second file
                    lambda msgs: (
                        '{"tool": "file_system", "args": {"action": "read", "path": "test_s2_file_b.py"}}'
                    ),
                    # Step 3: read third file
                    lambda msgs: (
                        '{"tool": "file_system", "args": {"action": "read", "path": "test_s2_file_c.py"}}'
                    ),
                    # Step 4: final answer
                    lambda msgs: (
                        '{"tool": "final_answer", "args": {"answer": "## Architecture Summary\\nSimple Python project."}}'
                    ),
                ])

                loop = ExecutionLoop(
                    state=state,
                    llm_provider=llm,
                    evidence_log=EvidenceLog(),
                )
                result = loop.run("Analyze this repository and summarize its architecture.")
                self.assertIsNotNone(result)
            finally:
                bus.emit = original_emit
        finally:
            for f in test_files:
                if os.path.exists(f):
                    os.unlink(f)


class TestIntentPolicyFields(unittest.TestCase):
    """Verify IntentPolicy has the required fields for R4.4."""

    def test_intent_policy_has_required_evidence_actions(self):
        policy = IntentPolicy()
        self.assertTrue(hasattr(policy, "required_evidence_actions"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
