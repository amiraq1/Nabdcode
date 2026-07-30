"""
R4.3 Strict Evidence Semantics Tests.

PATCH-R4.3 Protocol requirements:
  Step 1: Hard NUL rejection (4 tests: prefix, infix, suffix, only-NUL)
  Step 2: Strict evidence action semantics (edit != read)
  Step 3: Trusted metadata provenance (workspace_relative_path)
  Step 4: Fallback guard test (classify_intent raises AssertionError)
"""

import inspect
import sys
import os
import unittest
from typing import Any
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine._loop_helpers import _normalize_path, _check_required_target_in_evidence
from engine._loop_types import IntentPolicy


# =========================================================================
# Step 1: Hard NUL Rejection Tests
# =========================================================================

class TestNULRejectionHard(unittest.TestCase):
    """Step 1: Hard NUL byte rejection — strip/transform is forbidden."""

    def test_nul_prefix_rejected(self):
        """NUL byte at the start of a path must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _normalize_path("\0src/app.py")
        self.assertIn("NUL", str(ctx.exception),
                      f"Expected NUL in error message, got: {ctx.exception}")

    def test_nul_infix_rejected(self):
        """NUL byte in the middle of a path must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _normalize_path("src/\0app.py")
        self.assertIn("NUL", str(ctx.exception),
                      f"Expected NUL in error message, got: {ctx.exception}")

    def test_nul_suffix_rejected(self):
        """NUL byte at the end of a path must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _normalize_path("src/app.py\0")
        self.assertIn("NUL", str(ctx.exception),
                      f"Expected NUL in error message, got: {ctx.exception}")

    def test_only_nul_rejected(self):
        """Path consisting entirely of NUL bytes must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _normalize_path("\0\0\0")
        self.assertIn("NUL", str(ctx.exception),
                      f"Expected NUL in error message, got: {ctx.exception}")

    def test_nul_normal_path_still_works(self):
        """Normal paths without NUL still work correctly."""
        result = _normalize_path("src/app.py")
        self.assertEqual(result, "src/app.py")


# =========================================================================
# Step 2: Strict Evidence Action Semantics Tests
# =========================================================================

def make_record(tool: str, action: str, cmd: str, success: bool = True,
                workspace_relative_path: str = ""):
    return SimpleNamespace(
        tool=tool, action=action, command_or_path=cmd,
        success=success, workspace_relative_path=workspace_relative_path,
    )

class MockEvidenceLog:
    def __init__(self, records: list[Any]):
        self._records = records
    def get_records(self):
        return self._records


class TestStrictEvidenceActions(unittest.TestCase):
    """Step 2: evidence action must match policy.required_evidence_actions."""

    def test_read_action_satisfies_single_file_with_workspace_path(self):
        """read action with workspace_relative_path set must satisfy SINGLE_FILE_LOOKUP."""
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True,
                       workspace_relative_path="src/app.py"),
        ])
        actions = frozenset({"read", "view"})
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log, required_evidence_actions=actions,
        )
        self.assertTrue(ok, f"Expected read to satisfy, got: {reason}")

    def test_edit_action_does_not_satisfy_read(self):
        """edit action must NOT satisfy SINGLE_FILE_LOOKUP (requires read/view only)."""
        log = MockEvidenceLog([
            make_record("file_system", "edit", "src/app.py", success=True),
        ])
        actions = frozenset({"read", "view"})
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log, required_evidence_actions=actions,
        )
        self.assertFalse(ok, f"Expected edit to be rejected for read intent, got: {reason}")
        self.assertIn("not found", reason.lower())

    def test_write_action_does_not_satisfy_read(self):
        """write action must NOT satisfy SINGLE_FILE_LOOKUP."""
        log = MockEvidenceLog([
            make_record("file_system", "write", "src/app.py", success=True),
        ])
        actions = frozenset({"read", "view"})
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log, required_evidence_actions=actions,
        )
        self.assertFalse(ok, f"Expected write to be rejected, got: {reason}")

    def test_empty_actions_does_not_default(self):
        """PATCH-R4.4: Empty required_evidence_actions now rejects (fail-closed)."""
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log, required_evidence_actions=frozenset(),
        )
        self.assertFalse(ok, f"Expected empty actions to reject, got: {reason}")
        self.assertIn("INVALID_INTENT_POLICY", reason)

    def test_intent_policy_has_required_evidence_actions(self):
        """IntentPolicy must have required_evidence_actions field."""
        policy = IntentPolicy()
        self.assertTrue(hasattr(policy, "required_evidence_actions"),
                        "IntentPolicy missing required_evidence_actions")
        self.assertIsInstance(policy.required_evidence_actions, frozenset)


# =========================================================================
# Step 3: Trusted Metadata Provenance Tests
# =========================================================================

class TestTrustedMetadataProvenance(unittest.TestCase):
    """Step 3: workspace_relative_path preferred over command_or_path."""

    def test_workspace_relative_path_used_when_present(self):
        """When workspace_relative_path is set, it should be used for matching."""
        log = MockEvidenceLog([
            make_record(
                tool="file_system", action="read", cmd="legacy/path.py",
                success=True,
                workspace_relative_path="workspace/real/path.py",
            ),
        ])
        ok, reason = _check_required_target_in_evidence(
            "workspace/real/path.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertTrue(ok, f"Expected workspace_relative_path to match, got: {reason}")

    def test_command_or_path_fallback_rejected_when_no_workspace_path(self):
        """PATCH-R4.4: command_or_path fallback is REMOVED — reject if no workspace_relative_path."""
        log = MockEvidenceLog([
            make_record(
                tool="file_system", action="read", cmd="src/app.py",
                success=True,
                workspace_relative_path="",
            ),
        ])
        ok, reason = _check_required_target_in_evidence(
            "src/app.py", log,
            required_evidence_actions=frozenset({"read", "view"}),
        )
        self.assertFalse(ok, f"Expected reject (no workspace_relative_path), got: {reason}")
        self.assertIn("TRUSTED_TARGET_METADATA_MISSING", reason)

    def test_evidence_record_has_workspace_relative_path_field(self):
        """EvidenceRecord must have workspace_relative_path field."""
        from core.evidence import EvidenceRecord
        rec = EvidenceRecord(
            tool="file_system", command_or_path="src/app.py",
            action="read", success=True,
            workspace_relative_path="workspace/src/app.py",
        )
        self.assertEqual(rec.workspace_relative_path, "workspace/src/app.py")


# =========================================================================
# Step 4: Fallback Guard Test
# =========================================================================

class TestFallbackGuard(unittest.TestCase):
    """Step 4: Prove dynamic classification is dead in the production path.

    Monkeypatches classify_intent to raise AssertionError. If the production
    path (verify_fresh -> Verifier.verify -> check_investigation_gates) still
    calls classify_intent, the error will propagate. We test the chain by
    calling verify_fresh with intent param provided.
    """

    def test_production_path_does_not_call_classify_intent(self):
        """When intent is provided, classify_intent must NOT be called."""
        from core.evidence import EvidenceLog
        import core.investigation as _mod
        original = _mod.classify_intent

        self._classify_called = False
        def raising_classify(prompt):
            self._classify_called = True
            raise AssertionError(
                "classify_intent was called in the production path! "
                "This proves dynamic reclassification is still alive."
            )

        _mod.classify_intent = raising_classify
        try:
            log = EvidenceLog()
            log.record("file_system", "src/app.py", True, "content", action="read")

            from core.investigation import InvestigationIntent
            # Call verify_fresh with intent param provided
            result = log.verify_fresh(
                claim="I read src/app.py",
                require_tools=True,
                user_prompt="Read src/app.py",
                intent=InvestigationIntent.SINGLE_FILE_LOOKUP,
                required_target="",
            )
            # If classify_intent was called, raising_classify would have raised
            # AssertionError. If we reach here, classify_intent was NOT called.
            self.assertFalse(self._classify_called,
                            "classify_intent was called but didn't raise — monkeypatch failed")
            self.assertTrue(result.ok, f"verify_fresh should pass, got: {result.findings}")
        finally:
            _mod.classify_intent = original

    def test_fallback_classify_intent_dead_in_check_investigation_gates(self):
        """check_investigation_gates must use pre-classified intent, not re-classify."""
        from core.investigation import check_investigation_gates, InvestigationIntent
        import core.investigation as _mod
        original = _mod.classify_intent

        call_count = {"count": 0}
        def tracking_classify(prompt):
            call_count["count"] += 1
            return original(prompt)

        _mod.classify_intent = tracking_classify
        try:
            # Call with intent param provided
            passed, reason = check_investigation_gates(
                "any prompt", [],
                intent=InvestigationIntent.CHAT,
            )
            self.assertTrue(passed)
            # classify_intent should NOT have been called
            self.assertEqual(call_count["count"], 0,
                            f"classify_intent called {call_count['count']} time(s)")
        finally:
            _mod.classify_intent = original

    def test_both_classify_and_prompt_requires_dead_in_production_path(self):
        """Both classify_intent and _prompt_requires_investigation are DEAD
        in the verify_fresh -> Verifier.verify -> check_investigation_gates chain
        when intent is provided. Monkeypatch both to raise AssertionError.
        """
        from core.evidence import EvidenceLog
        from core.investigation import InvestigationIntent
        import core.investigation as _inv_mod
        import engine._loop_helpers as _lh_mod

        _ci_original = _inv_mod.classify_intent
        _pri_original = _lh_mod._prompt_requires_investigation

        called = {"classify_intent": False, "_prompt_requires_investigation": False}

        def raising_classify(prompt):
            called["classify_intent"] = True
            raise AssertionError("classify_intent called in production path!")

        def raising_prompt_requires(text, has_active_goal=False):
            called["_prompt_requires_investigation"] = True
            raise AssertionError("_prompt_requires_investigation called in production path!")

        _inv_mod.classify_intent = raising_classify
        _lh_mod._prompt_requires_investigation = raising_prompt_requires
        try:
            log = EvidenceLog()
            log.record("file_system", "src/app.py", True, "content", action="read")

            result = log.verify_fresh(
                claim="I read src/app.py",
                require_tools=True,
                user_prompt="Read src/app.py",
                intent=InvestigationIntent.SINGLE_FILE_LOOKUP,
                required_target="",
            )
            self.assertFalse(called["classify_intent"],
                            "classify_intent was called in the production chain")
            self.assertFalse(called["_prompt_requires_investigation"],
                            "_prompt_requires_investigation was called in the production chain")
            self.assertTrue(result.ok, f"verify_fresh should pass, got: {result.findings}")
        finally:
            _inv_mod.classify_intent = _ci_original
            _lh_mod._prompt_requires_investigation = _pri_original

    def test_prompt_requires_investigation_exists_as_legacy_helper(self):
        """_prompt_requires_investigation still exists as a legacy helper."""
        import engine._loop_helpers as _lh
        self.assertTrue(hasattr(_lh, "_prompt_requires_investigation"),
                        "legacy helper should still exist for backward compat")


# =========================================================================
# Live Smoke — Normalize path with NUL rejection
# =========================================================================

class TestLiveSmokeR43(unittest.TestCase):
    """R4.3 native live smoke — no monkeypatching."""

    def test_normalize_nul_rejection_works(self):
        with self.assertRaises(ValueError) as ctx:
            _normalize_path("test\0file.py")
        self.assertIn("NUL", str(ctx.exception))

    def test_normalize_clean_path_works(self):
        result = _normalize_path("core/evidence.py")
        self.assertEqual(result, "core/evidence.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
