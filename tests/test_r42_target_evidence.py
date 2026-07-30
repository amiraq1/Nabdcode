"""
R4.2 Target-Evidence Enforcement Tests.

PATCH-R4.2 Protocol requirements:
  Step 1: Trusted evidence target comparison
  Step 2: Eradicate dynamic reclassification
  Step 3: Extreme normalization tests
  Step 4: 10 Runtime Behavioral Target Tests
"""

import inspect
import sys
import os
import unittest
from typing import Any, Dict, List
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# =========================================================================
# Step 3: Extreme Normalization Tests
# =========================================================================

from engine._loop_helpers import _normalize_path, _check_required_target_in_evidence


class TestNormalizePathExtreme(unittest.TestCase):
    """Step 3: Extreme edge-case tests for _normalize_path."""

    def test_normal_basic(self):
        self.assertEqual(_normalize_path("src/app.py"), "src/app.py")

    def test_normal_dot_slash(self):
        self.assertEqual(_normalize_path("./src/app.py"), "src/app.py")

    def test_normal_double_dot_slash(self):
        self.assertEqual(_normalize_path("././src/app.py"), "src/app.py")

    def test_windowss_backslash(self):
        """C:\\Windows\\file -> Windows/file"""
        self.assertEqual(_normalize_path("C:\\Windows\\file"), "C:/Windows/file")

    def test_forward_backslash_mixed(self):
        self.assertEqual(_normalize_path("src\\utils\\app.py"), "src/utils/app.py")

    def test_double_forward_slash(self):
        """Collapse double slashes"""
        self.assertEqual(_normalize_path("src//app.py"), "src/app.py")

    def test_triple_forward_slash(self):
        self.assertEqual(_normalize_path("src///app.py"), "src/app.py")

    def test_inline_dot_component(self):
        """Path with . component in the middle is collapsed."""
        self.assertEqual(_normalize_path("./core/./utils/file.py"), "core/utils/file.py")

    def test_single_dot(self):
        """Single dot normalizes to empty string"""
        self.assertEqual(_normalize_path("."), "")

    def test_rejects_absolute(self):
        with self.assertRaises(ValueError):
            _normalize_path("/etc/passwd")

    def test_rejects_traversal(self):
        with self.assertRaises(ValueError):
            _normalize_path("../secret.txt")

    def test_rejects_deep_traversal(self):
        with self.assertRaises(ValueError):
            _normalize_path("src/../../secret.txt")

    def test_rejects_home_dir(self):
        with self.assertRaises(ValueError):
            _normalize_path("~/secret.txt")

    def test_rejects_home_with_path(self):
        with self.assertRaises(ValueError):
            _normalize_path("~/projects/file.py")

    def test_nul_character_in_path(self):
        """PATCH-R4.3: NUL characters are HARD-REJECTED."""
        with self.assertRaises(ValueError) as ctx:
            _normalize_path("src\0/app.py")
        self.assertIn("NUL", str(ctx.exception))

    def test_nul_only_path(self):
        """PATCH-R4.3: Path with only NUL is HARD-REJECTED."""
        with self.assertRaises(ValueError) as ctx:
            _normalize_path("\0\0\0")
        self.assertIn("NUL", str(ctx.exception))

    def test_empty_string(self):
        self.assertEqual(_normalize_path(""), "")

    def test_same_basename_diff_dir(self):
        """src/config.py != tests/config.py -- full path comparison"""
        src = _normalize_path("src/config.py")
        test = _normalize_path("tests/config.py")
        self.assertNotEqual(src, test)
        self.assertEqual(src, "src/config.py")
        self.assertEqual(test, "tests/config.py")

    def test_unc_path_forward(self):
        """//server/share should be rejected"""
        with self.assertRaises(ValueError):
            _normalize_path("//server/share/file.py")

    def test_unc_path_backslash(self):
        """\\\\server\\share should be rejected"""
        with self.assertRaises(ValueError):
            _normalize_path("\\\\server\\share\\file.py")

    def test_quoted_path_no_space(self):
        """Quoted path without spaces."""
        result = _normalize_path('"src/app.py"')
        self.assertEqual(result, '"src/app.py"')

    def test_quoted_path_with_space(self):
        """Quoted path with spaces -- quotes are preserved as they wrap the path."""
        result = _normalize_path('"src/my file.py"')
        self.assertEqual(result, '"src/my file.py"')

    def test_relative_complex(self):
        val = _normalize_path("./core/./utils/file.py")
        self.assertEqual(val, "core/utils/file.py")


# =========================================================================
# Mock helpers
# =========================================================================

def make_record(tool: str, action: str, command_or_path: str, success: bool = True):
    """Create a minimal record-like object."""
    return SimpleNamespace(
        tool=tool,
        action=action,
        command_or_path=command_or_path,
        success=success,
    )


class MockEvidenceLog:
    """Minimal EvidenceLog mock for testing _check_required_target_in_evidence."""
    def __init__(self, records: list[Any]):
        self._records = records
    def get_records(self):
        return self._records


# =========================================================================
# Step 1 & 4: Trusted Evidence Target Comparison + 10 Behavioral Tests
# =========================================================================

class TestCheckRequiredTargetInEvidence(unittest.TestCase):
    """Step 1: Trusted Evidence Target Comparison + Step 4: 10 tests."""

    # Test 1: Correct target passes
    def test_01_correct_target_passes(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("src/app.py", log)
        self.assertTrue(ok, f"Expected pass, got: {reason}")

    # Test 2: Unrelated target rejects
    def test_02_unrelated_target_rejects(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("other/file.txt", log)
        self.assertFalse(ok, f"Expected reject, got: {reason}")

    # Test 3: Same basename in wrong dir rejects
    def test_03_same_basename_wrong_dir_rejects(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "tests/config.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("src/config.py", log)
        self.assertFalse(ok, "Expected reject (src/config.py != tests/config.py)")
        self.assertIn("not found", reason.lower())

    # Test 4: Failed read evidence rejects
    def test_04_failed_read_rejects(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/app.py", success=False),
        ])
        ok, reason = _check_required_target_in_evidence("src/app.py", log)
        self.assertFalse(ok, f"Expected reject (failed read), got: {reason}")

    # Test 5: Directory list does not satisfy file read
    def test_05_directory_list_does_not_satisfy(self):
        log = MockEvidenceLog([
            make_record("file_system", "list", "src", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("src/app.py", log)
        self.assertFalse(ok, f"Expected reject (list != read), got: {reason}")

    # Test 6: LLM claiming without trusted metadata rejects
    def test_06_llm_claim_without_metadata_rejects(self):
        log = MockEvidenceLog([
            make_record("execute_shell", "run", "cat src/app.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("src/app.py", log)
        self.assertFalse(ok, "Expected reject (shell cat != file_system read)")

    # Test 7: Missing target rejects
    def test_07_missing_target_rejects(self):
        log = MockEvidenceLog([])
        ok, reason = _check_required_target_in_evidence("src/app.py", log)
        self.assertFalse(ok, f"Expected reject (empty evidence), got: {reason}")

    # Test 8: Normalized matching (./ prefix)
    def test_08_normalized_matching_dot_slash(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "./src/app.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("src/app.py", log)
        self.assertTrue(ok, f"Expected pass (normalized), got: {reason}")

    # Test 9: No target required passes
    def test_09_no_target_required_passes(self):
        log = MockEvidenceLog([])
        ok, reason = _check_required_target_in_evidence("", log)
        self.assertTrue(ok, f"Expected pass (no target), got: {reason}")

    # Test 10: Backslash path matches
    def test_10_backslash_path_matches(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "src\\app.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("src/app.py", log)
        self.assertTrue(ok, f"Expected pass (backslash norm), got: {reason}")


# =========================================================================
# Step 2: Dynamic Reclassification Tests
# =========================================================================

class TestCheckInvestigationGatesIntentParam(unittest.TestCase):
    """Step 2: check_investigation_gates accepts pre-classified intent."""

    def test_intent_param_used_when_provided(self):
        """Given intent param, overrides classification."""
        from core.investigation import check_investigation_gates, InvestigationIntent
        chat_prompt = "hello how are you"
        passed, reason = check_investigation_gates(
            chat_prompt, [],
            intent=InvestigationIntent.REPOSITORY_INVESTIGATION,
        )
        self.assertFalse(passed, f"Expected fail with multi-stage override, got: {reason}")
        self.assertIn("investigation", reason.lower(),
                      f"Should mention investigation in: {reason}")

    def test_intent_param_chat_bypasses(self):
        """CHAT intent bypasses gates regardless of prompt."""
        from core.investigation import check_investigation_gates, InvestigationIntent
        passed, reason = check_investigation_gates(
            "analyze this entire repository", [],
            intent=InvestigationIntent.CHAT,
        )
        self.assertTrue(passed, f"Expected pass with CHAT intent, got: {reason}")

    def test_investigation_intent_enum_accepted(self):
        """InvestigationIntent enum values work with check_investigation_gates."""
        from core.investigation import check_investigation_gates, InvestigationIntent
        passed, reason = check_investigation_gates(
            "analyze the repository", [],
            intent=InvestigationIntent.SINGLE_FILE_LOOKUP,
        )
        self.assertTrue(passed, f"Expected pass for SINGLE_FILE_LOOKUP, got: {reason}")


class TestVerifyFreshIntentParam(unittest.TestCase):
    """Step 2: verify_fresh and Verifier.verify accept intent param."""

    def test_verify_fresh_signature_has_intent(self):
        from core.evidence import EvidenceLog
        sig = inspect.signature(EvidenceLog.verify_fresh)
        self.assertIn("intent", sig.parameters,
                      f"verify_fresh must accept 'intent'. Sig: {sig}")

    def test_verifier_verify_signature_has_intent(self):
        from core.evidence import Verifier
        sig = inspect.signature(Verifier.verify)
        self.assertIn("intent", sig.parameters,
                      f"Verifier.verify must accept 'intent'. Sig: {sig}")

    def test_check_investigation_gates_signature_has_intent(self):
        from core.investigation import check_investigation_gates
        sig = inspect.signature(check_investigation_gates)
        self.assertIn("intent", sig.parameters,
                      f"check_investigation_gates must accept 'intent'. Sig: {sig}")


class TestNoClassifyIntentInChokePoints(unittest.TestCase):
    """Step 2: classify_intent NOT called when intent param provided."""

    def test_check_investigation_gates_uses_intent_param(self):
        """When intent is provided, classify_intent must NOT be called."""
        from core.investigation import (
            check_investigation_gates, InvestigationIntent, classify_intent as _ci
        )
        import core.investigation as _mod
        original = _mod.classify_intent

        call_count = {"count": 0}
        def tracking_classify(prompt):
            call_count["count"] += 1
            return original(prompt)

        _mod.classify_intent = tracking_classify
        try:
            passed, reason = check_investigation_gates(
                "any prompt", [],
                intent=InvestigationIntent.CHAT,
            )
            self.assertTrue(passed)
            self.assertEqual(call_count["count"], 0,
                            f"classify_intent called {call_count['count']} time(s)")
        finally:
            _mod.classify_intent = original


# =========================================================================
# Step 5: Native Live Smoke (no monkeypatching)
# =========================================================================

class TestNativeLiveSmoke(unittest.TestCase):
    """Verify R4.2 changes work without monkeypatching."""

    def test_normalize_path_extreme_coverage(self):
        cases = [
            ("src/app.py", "src/app.py"),
            ("./src/app.py", "src/app.py"),
            ("src\\utils\\app.py", "src/utils/app.py"),
            ("src//app.py", "src/app.py"),
            ("./core/./utils/file.py", "core/utils/file.py"),
            (".", ""),
            ("", ""),
        ]
        for inp, expected in cases:
            with self.subTest(path=inp):
                result = _normalize_path(inp)
                self.assertEqual(result, expected)

    def test_normalize_path_rejection_coverage(self):
        rejections = [
            "/etc/passwd",
            "../secret.txt",
            "src/../../secret.txt",
            "~/secret.txt",
            "//server/share/file.py",
            "\\\\server\\share\\file.py",
        ]
        for inp in rejections:
            with self.subTest(path=inp):
                with self.assertRaises(ValueError):
                    _normalize_path(inp)

    def test_target_match_normalized(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "core/loop.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("core/loop.py", log)
        self.assertTrue(ok, f"Expected pass, got: {reason}")

    def test_target_mismatch_same_basename(self):
        log = MockEvidenceLog([
            make_record("file_system", "read", "src/config.py", success=True),
        ])
        ok, reason = _check_required_target_in_evidence("tests/config.py", log)
        self.assertFalse(ok, "Should reject: tests/config.py != src/config.py")
        self.assertIn("not found", reason.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
