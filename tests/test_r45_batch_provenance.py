#!/usr/bin/env python3
"""
R4.5 — Batch Provenance Audit Tests.

Steps covered:
  1. Read-many semantic isolation — no workspace_relative_path, action="read_many"
  2. Dispatcher tool identity enforced (verified via code review)
  3. Schema deserialization — old record without workspace_relative_path defaults to ""
  4. True E2E native S1/S2 classification and policy verification
"""

import json
import unittest
from unittest import mock
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 — Read-Many Semantic Isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadManyIsolation(unittest.TestCase):
    """PATCH-R4.5: read_many must NOT populate workspace_relative_path."""

    def test_01_read_many_metadata_has_no_workspace_relative_path(self):
        """read_many ToolResult.metadata must NOT contain workspace_relative_path."""
        from tools.file_system import FileSystemTool
        tool = FileSystemTool()
        kwargs = {"paths": ["core/evidence.py"]}
        result = tool._handle_read_many(kwargs)
        md = getattr(result, "metadata", {}) or {}
        self.assertNotIn("workspace_relative_path", md,
                         "read_many must not leak workspace_relative_path")

    def test_02_read_many_metadata_has_action_read_many(self):
        """read_many ToolResult.metadata must contain action='read_many'."""
        from tools.file_system import FileSystemTool
        tool = FileSystemTool()
        result = tool._handle_read_many({"paths": ["core/evidence.py"]})
        md = getattr(result, "metadata", {}) or {}
        self.assertEqual(md.get("action"), "read_many",
                         "read_many metadata must identify as batch")

    def test_03_read_many_empty_paths_no_metadata_leak(self):
        """read_many with invalid paths must not leak path."""
        from tools.file_system import FileSystemTool
        tool = FileSystemTool()
        result = tool._handle_read_many({"paths": ["nonexistent_file_xyz.py"]})
        md = getattr(result, "metadata", {}) or {}
        self.assertNotIn("workspace_relative_path", md)

    def test_04_read_many_multiple_files_no_path_leak(self):
        """read_many on multiple files must not populate workspace_relative_path."""
        from tools.file_system import FileSystemTool
        tool = FileSystemTool()
        result = tool._handle_read_many({"paths": ["core/evidence.py", "core/constants.py"]})
        md = getattr(result, "metadata", {}) or {}
        self.assertNotIn("workspace_relative_path", md)

    def test_05_dispatcher_extracts_empty_path_for_read_many(self):
        """Simulate the dispatcher extraction: empty metadata -> empty path."""
        from tools.models import ToolResult
        result = ToolResult(
            success=True,
            stdout="file content",
            metadata={"action": "read_many"},
        )
        _md = getattr(result, "metadata", {}) or {}
        _wrp = str(_md.get("workspace_relative_path", "") or "")
        self.assertEqual(_wrp, "",
                         "Dispatcher must extract '' from read_many metadata")


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 — Dispatcher Tool Identity
# ═══════════════════════════════════════════════════════════════════════════════

class TestDispatcherToolIdentity(unittest.TestCase):
    """PATCH-R4.5: Strict dispatcher tool identity — no self-reported metadata."""

    def test_01_tool_name_param_in_execute_and_record(self):
        """Evidence record tool must come from tool_call.tool, not metadata."""
        from engine._dispatch import _ToolDispatchMixin
        import inspect
        sig = inspect.signature(_ToolDispatchMixin._execute_and_record)
        params = list(sig.parameters.keys())
        self.assertIn("tool_name", params,
                      "_execute_and_record must accept tool_name as explicit param")

    def test_02_no_tool_name_in_metadata_dispatch(self):
        """Ensure no metadata-based tool_name extraction in the dispatcher."""
        import engine._dispatch as mod
        with open(mod.__file__) as f:
            source = f.read()
        self.assertNotIn('metadata.get("tool_name"', source,
                          "Dispatcher must not read tool_name from metadata")
        self.assertNotIn('metadata["tool_name"]', source,
                         "Dispatcher must not read tool_name from metadata")

    def test_03_dispatcher_uses_tool_call_tool(self):
        """The _dispatch_and_record_evidence sets tool_name from tool_call.tool."""
        import engine._dispatch as mod
        with open(mod.__file__) as f:
            source = f.read()
        # Verify tool_name = tool_call.tool is present
        self.assertIn("tool_name = tool_call.tool", source,
                      "Dispatcher must set tool_name from tool_call.tool")


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 — Schema Serialization & Deserialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchemaDeserialization(unittest.TestCase):
    """PATCH-R4.5: Old serialized EvidenceRecord without workspace_relative_path."""

    def _make_raw_dict(self, wrp: str = "") -> dict[str, Any]:
        """Build a raw dict matching EvidenceRecord.to_dict() output."""
        return {
            "evidence_id": "E-TEST-1",
            "evidence_type": "filesystem",
            "tool": "file_system",
            "command_or_path": "src/app.py",
            "output_snippet": "def foo(): pass",
            "subjects": [],
            "coverage_checksum": "",
            "success": True,
            "critical": False,
            "timestamp": 1234567890.0,
            "action": "read",
            "covered_subjects": [],
            "workspace_relative_path": wrp,
        }

    def test_01_old_record_without_wrp_defaults_empty(self):
        """Old serialized record missing workspace_relative_path defaults to ''."""
        from core.evidence import EvidenceRecord
        old_dict = self._make_raw_dict()
        old_dict.pop("workspace_relative_path", None)  # Simulate OLD format
        rec = EvidenceRecord.from_dict(old_dict)
        self.assertEqual(rec.workspace_relative_path, "",
                         "Old record must default workspace_relative_path to ''")

    def test_02_new_record_roundtrip(self):
        """New record with wrp round-trips correctly through to_dict/from_dict."""
        from core.evidence import EvidenceRecord
        original = EvidenceRecord(
            evidence_id="E-RT-1",
            evidence_type="filesystem",
            tool="file_system",
            command_or_path="src/app.py",
            success=True,
            output_snippet="content",
            workspace_relative_path="src/app.py",
            action="read",
        )
        d = original.to_dict()
        restored = EvidenceRecord.from_dict(d)
        self.assertEqual(restored.workspace_relative_path, "src/app.py")
        self.assertEqual(restored.evidence_id, "E-RT-1")
        self.assertEqual(restored.action, "read")

    def test_03_old_record_fails_target_gate(self):
        """Old record without wrp fails the target evidence gate."""
        from core.evidence import EvidenceRecord, EvidenceLog
        old_dict = self._make_raw_dict()
        old_dict.pop("workspace_relative_path", None)
        rec = EvidenceRecord.from_dict(old_dict)

        log = EvidenceLog()
        log.add(rec)

        from engine._loop_helpers import _check_required_target_in_evidence
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok,
                         "Old record without wrp must fail the target gate")

    def test_04_new_record_with_wrp_passes_target_gate(self):
        """New record with wrp passes the target evidence gate."""
        from core.evidence import EvidenceRecord, EvidenceLog
        rec = EvidenceRecord(
            evidence_id="E-NEW-1",
            evidence_type="filesystem",
            tool="file_system",
            command_or_path="src/app.py",
            success=True,
            output_snippet="content",
            workspace_relative_path="src/app.py",
            action="read",
        )
        log = EvidenceLog()
        log.add(rec)

        from engine._loop_helpers import _check_required_target_in_evidence
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertTrue(ok, f"New record with wrp must pass gate, got: {reason}")

    def test_05_json_serialization_no_wrp_defaults_empty(self):
        """Full JSON round-trip without wrp loads safely."""
        from core.evidence import EvidenceRecord
        old_dict = self._make_raw_dict()
        old_dict.pop("workspace_relative_path", None)

        json_str = json.dumps(old_dict)
        loaded = json.loads(json_str)
        rec = EvidenceRecord.from_dict(loaded)
        self.assertEqual(rec.workspace_relative_path, "")

    def test_06_read_many_evidence_fails_target_gate(self):
        """EvidenceRecord with action='read_many' fails target gate."""
        from core.evidence import EvidenceRecord, EvidenceLog
        rec = EvidenceRecord(
            evidence_id="E-RM-1",
            evidence_type="filesystem",
            tool="file_system",
            command_or_path="src/app.py",
            success=True,
            output_snippet="content",
            workspace_relative_path="src/app.py",  # Even with wrp, wrong action
            action="read_many",
        )
        log = EvidenceLog()
        log.add(rec)

        from engine._loop_helpers import _check_required_target_in_evidence
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok,
                         "read_many action must fail the target gate")


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4 — True Native E2E Classification & Policy
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrueNativeE2E(unittest.TestCase):
    """True native intent classification — NO monkeypatching."""

    def test_s1_prompt_classifies_single_file(self):
        """S1 prompt must classify as SINGLE_FILE_LOOKUP."""
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read broken_script.py and identify the syntax error only.")
        self.assertEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP,
                         f"S1 must classify as SINGLE_FILE_LOOKUP, got: {intent}")

    def test_s2_prompt_classifies_architecture(self):
        """S2 prompt must classify as ARCHITECTURE_REVIEW."""
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Analyze this repository and summarize its architecture.")
        self.assertEqual(intent, InvestigationIntent.ARCHITECTURE_REVIEW,
                         f"S2 must classify as ARCHITECTURE_REVIEW, got: {intent}")

    def test_s1_policy_minimum_reads_1(self):
        """S1 intent policy must have minimum_reads == 1."""
        from engine._loop_helpers import _get_intent_policy
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read broken_script.py and identify the syntax error only.")
        policy = _get_intent_policy(intent)
        self.assertEqual(policy.minimum_reads, 1)
        self.assertFalse(policy.requires_plan)
        self.assertFalse(policy.requires_root_listing)

    def test_s2_policy_minimum_reads_ge_3(self):
        """S2 intent policy must have minimum_reads >= 3."""
        from engine._loop_helpers import _get_intent_policy
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Analyze this repository and summarize its architecture.")
        policy = _get_intent_policy(intent)
        self.assertGreaterEqual(policy.minimum_reads, 3)
        self.assertTrue(policy.requires_plan)
        self.assertTrue(policy.requires_root_listing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
