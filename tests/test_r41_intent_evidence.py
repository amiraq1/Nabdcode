"""
PATCH-R4.1: Intent-Evidence alignment tests.

Covers: verify_fresh policy wiring, _normalize_path() edge cases,
and strict relative path matching.

Run:  PYTHONPATH=/data/data/com.termux/files/home/smart-agent \
       python /tmp/r41_intent_evidence_tests.py
"""

import os
import sys
import unittest
from pathlib import Path

# Keep the test runnable in Termux, CI, and a local checkout alike.
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ====================================================================
# Test _normalize_path() — strict relative path normalization
# ====================================================================
class TestPathNormalization(unittest.TestCase):
    """_normalize_path must normalize, reject absolutes, reject traversal."""

    def _get_norm(self):
        from engine._loop_helpers import _normalize_path
        return _normalize_path

    def test_normal_basic(self):
        _n = self._get_norm()
        self.assertEqual(_n("src/app.py"), "src/app.py")

    def test_strip_dot_slash(self):
        _n = self._get_norm()
        self.assertEqual(_n("./src/app.py"), "src/app.py")

    def test_strip_multiple_dot_slash(self):
        _n = self._get_norm()
        self.assertEqual(_n("././src/app.py"), "src/app.py")

    def test_backslash_normalization(self):
        _n = self._get_norm()
        self.assertEqual(_n("core\\utils\\h.py"), "core/utils/h.py")

    def test_backslash_and_dot_slash(self):
        _n = self._get_norm()
        self.assertEqual(_n(".\\core\\file.py"), "core/file.py")

    def test_empty_string(self):
        _n = self._get_norm()
        self.assertEqual(_n(""), "")

    def test_rejects_absolute_path(self):
        _n = self._get_norm()
        with self.assertRaises(ValueError):
            _n("/etc/passwd.txt")

    def test_rejects_traversal(self):
        _n = self._get_norm()
        with self.assertRaises(ValueError):
            _n("../secret.txt")

    def test_rejects_deep_traversal(self):
        _n = self._get_norm()
        with self.assertRaises(ValueError):
            _n("../../etc/passwd.txt")

    def test_does_not_use_path_resolve(self):
        """_normalize_path must NOT use Path.resolve() (real filesystem)."""
        import inspect
        from engine._loop_helpers import _normalize_path
        source = inspect.getsource(_normalize_path)
        self.assertNotIn("Path.resolve", source,
                         "_normalize_path must not use Path.resolve()")
        self.assertNotIn(".resolve(", source,
                         "_normalize_path must not call resolve()")


# ====================================================================
# Test verify_fresh policy wiring
# ====================================================================
class TestVerifyFreshPolicyWiring(unittest.TestCase):
    """verify_fresh must accept and forward IntentPolicy params."""

    def test_verify_fresh_accepts_policy_params(self):
        """verify_fresh() signature must include IntentPolicy params."""
        import inspect
        from core.evidence import EvidenceLog
        sig = inspect.signature(EvidenceLog.verify_fresh)
        params = list(sig.parameters.keys())
        self.assertIn("minimum_reads", params,
                      "verify_fresh must accept minimum_reads")
        self.assertIn("requires_root_listing", params,
                      "verify_fresh must accept requires_root_listing")
        self.assertIn("required_target", params,
                      "verify_fresh must accept required_target")

    def test_verifier_verify_accepts_policy_params(self):
        """Verifier.verify() must accept and forward IntentPolicy params."""
        import inspect
        from core.evidence import Verifier
        sig = inspect.signature(Verifier.verify)
        params = list(sig.parameters.keys())
        self.assertIn("minimum_reads", params,
                      "Verifier.verify must accept minimum_reads")
        self.assertIn("requires_root_listing", params,
                      "Verifier.verify must accept requires_root_listing")
        self.assertIn("required_target", params,
                      "Verifier.verify must accept required_target")

    def test_check_investigation_gates_accepts_params(self):
        """check_investigation_gates must accept IntentPolicy params."""
        import inspect
        from core.investigation import check_investigation_gates
        sig = inspect.signature(check_investigation_gates)
        params = list(sig.parameters.keys())
        self.assertIn("minimum_reads", params,
                      "check_investigation_gates must accept minimum_reads")
        self.assertIn("requires_root_listing", params,
                      "check_investigation_gates must accept requires_root_listing")
        self.assertIn("required_target", params,
                      "check_investigation_gates must accept required_target")


# ====================================================================
# Test _emit_final passes policy to verify_fresh
# ====================================================================
class TestEmitFinalPolicyPassing(unittest.TestCase):
    """_emit_final must pass IntentPolicy params to verify_fresh."""

    def test_emit_final_passes_policy_params(self):
        """Verify by checking _convergence.py source for the policy params."""
        import inspect
        with open(
            os.path.join(PROJECT_ROOT, "engine", "_convergence.py"), "r"
        ) as f:
            source = f.read()
        # Check that the verify_fresh call includes the policy params
        self.assertIn(
            "minimum_reads=_vf_min_reads",
            source,
            "_emit_final must pass minimum_reads to verify_fresh",
        )
        self.assertIn(
            "requires_root_listing=_vf_root_list",
            source,
            "_emit_final must pass requires_root_listing to verify_fresh",
        )
        self.assertIn(
            "required_target=_vf_target",
            source,
            "_emit_final must pass required_target to verify_fresh",
        )


# ====================================================================
# Main runner
# ====================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
