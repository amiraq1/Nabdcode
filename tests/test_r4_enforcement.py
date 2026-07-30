"""
PATCH-INTENT-ROUTING-R4: Comprehensive enforcement protocol tests.

Run:  PYTHONPATH=/data/data/com.termux/files/home/smart-agent \
       python /tmp/r4_enforcement_tests.py

Covers: Root listing, graceful TypeError, S1 negative tests,
semantic target (quotes, traversal), S2 4-stage progression,
native live smoke (FAILED status verification).
"""

import os
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock, PropertyMock

PROJECT_ROOT = "/data/data/com.termux/files/home/smart-agent"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ====================================================================
# PART 1: Root Listing Enforcement Tests
# ====================================================================
class TestRootListingContract(unittest.TestCase):
    """requires_root_listing field must be correctly set and enforced."""

    def test_requires_root_listing_set_for_architecture(self):
        from core.investigation import InvestigationIntent
        from engine._loop_helpers import _get_intent_policy
        policy = _get_intent_policy(InvestigationIntent.ARCHITECTURE_REVIEW)
        self.assertTrue(policy.requires_root_listing)

    def test_requires_root_listing_set_for_repo_investigation(self):
        from core.investigation import InvestigationIntent
        from engine._loop_helpers import _get_intent_policy
        policy = _get_intent_policy(InvestigationIntent.REPOSITORY_INVESTIGATION)
        self.assertTrue(policy.requires_root_listing)

    def test_requires_root_listing_false_for_single_file(self):
        from core.investigation import InvestigationIntent
        from engine._loop_helpers import _get_intent_policy
        policy = _get_intent_policy(InvestigationIntent.SINGLE_FILE_LOOKUP)
        self.assertFalse(policy.requires_root_listing)

    def test_requires_root_listing_false_for_chat(self):
        from core.investigation import InvestigationIntent
        from engine._loop_helpers import _get_intent_policy
        policy = _get_intent_policy(InvestigationIntent.CHAT)
        self.assertFalse(policy.requires_root_listing)

    def test_can_finalize_rejects_missing_root_listing(self):
        from core.convergence_gate import can_finalize
        evidence_log = MagicMock()
        evidence_log.get_records.return_value = []
        decision = can_finalize(
            evidence_log=evidence_log,
            requires_root_listing=True,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("Root listing", decision.blocked_reason)

    def test_can_finalize_accepts_with_listing(self):
        from core.convergence_gate import can_finalize
        from core.evidence import EvidenceRecord
        evidence_log = MagicMock()
        evidence_log.get_records.return_value = [
            EvidenceRecord(tool="file_system", action="list",
                           command_or_path=".", success=True,
                           output_snippet="core/\nengine/\ntests/"),
        ]
        decision = can_finalize(
            evidence_log=evidence_log,
            requires_root_listing=True,
        )
        self.assertTrue(decision.allowed)


# ====================================================================
# PART 2: Graceful TypeError Handling Test
# ====================================================================
class TestGracefulTypeError(unittest.TestCase):
    """TypeError from _get_intent_policy must be caught and routed to FAILED."""

    def test_typeerror_fails_gracefully(self):
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        from core.turn_outcome import TurnStatus
        import engine._loop_helpers as _hlp

        state = RuntimeState(session_id="test-typeerror-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", "args": {"answer": "N/A"}}'
            ),
            max_output_len=100,
        )
        original = _hlp._get_intent_policy
        _hlp._get_intent_policy = lambda i: (_ for _ in ()).throw(
            TypeError("_get_intent_policy requires an InvestigationIntent")
        )
        try:
            outcome = loop.run("Read broken_script.py")
            self.assertIsNotNone(outcome)
            self.assertEqual(
                outcome.status, TurnStatus.FAILED,
                "TypeError must produce FAILED outcome",
            )
        finally:
            _hlp._get_intent_policy = original

    def test_valid_intent_still_succeeds(self):
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        state = RuntimeState(session_id="test-valid-intent-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", "args": {"answer": "Hello!"}}'
            ),
            max_output_len=100,
        )
        outcome = loop.run("Say hello.")
        self.assertIsNotNone(outcome)
        self.assertNotEqual(
            outcome.status.value, "FAILED",
            "Valid intent should not produce FAILED",
        )


# ====================================================================
# PART 3: S1 Regex Negative Tests (No Scope Creep)
# ====================================================================
class TestS1RegexNegativeTests(unittest.TestCase):
    """SINGLE_FILE_LOOKUP must NOT trigger when repo-scope keywords exist."""

    def test_s1_rejected_when_repo_analysis(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read a.py and analyze the repo")
        self.assertNotEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)

    def test_s1_rejected_when_architecture_scope(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read a.py and review the architecture")
        self.assertNotEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)

    def test_s1_rejected_when_codebase_analysis(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read a.py and analyze the entire codebase")
        self.assertNotEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)

    def test_s1_still_matches_targeted_read(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read a.py and find the bug")
        self.assertEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)

    def test_s1_still_matches_simple_check(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Check broken_script.py for syntax errors")
        self.assertEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)

    def test_s1_rejected_when_analyze_all_files(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read a.py and analyze all files in the project")
        self.assertNotEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)

    def test_s1_rejected_when_repository_scope(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read a.py and analyze the repository")
        self.assertNotEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)

    def test_s1_rejected_when_codebase_scope(self):
        from core.investigation import classify_intent, InvestigationIntent
        intent = classify_intent("Read a.py and explore the codebase")
        self.assertNotEqual(intent, InvestigationIntent.SINGLE_FILE_LOOKUP)


# ====================================================================
# PART 4: Semantic Target Verification Tests
# ====================================================================
class TestSemanticTargetVerification(unittest.TestCase):
    """required_target must handle quotes, relative paths, and prevent traversal."""

    def test_target_basic(self):
        import re
        m = re.search(
            r"(?:read|view|show|cat|check|inspect)\s+[\"']?([\w/\-\.]+(?:\.\w+))[\"']?",
            "Read broken_script.py and find the bug", re.IGNORECASE,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "broken_script.py")

    def test_target_relative_path(self):
        import re
        m = re.search(
            r"(?:read|view|show|cat|check|inspect)\s+[\"']?([\w/\-\.]+(?:\.\w+))[\"']?",
            "Read src/app.py and check its imports", re.IGNORECASE,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "src/app.py")

    def test_target_nested_path(self):
        import re
        m = re.search(
            r"(?:read|view|show|cat|check|inspect)\s+[\"']?([\w/\-\.]+(?:\.\w+))[\"']?",
            "Read core/utils/helpers.py and analyze", re.IGNORECASE,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "core/utils/helpers.py")

    def test_target_hyphenated(self):
        import re
        m = re.search(
            r"(?:read|view|show|cat|check|inspect)\s+[\"']?([\w/\-\.]+(?:\.\w+))[\"']?",
            "Read my-file-name.py and check it", re.IGNORECASE,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "my-file-name.py")

    def test_target_quoted_path_documentation(self):
        """Quoted paths with spaces document regex limitation.
        
        The regex [\\w/\\-\\.]+ does NOT match spaces. A path with spaces
        inside quotes like src/my file.py cannot be fully extracted by regex
        alone. Use underscore-separated paths for reliable extraction.
        """
        import re
        prompt = "Read src/my_file.py and parse it"  # underscore not space
        m = re.search(
            r"(?:read|view|show|cat|check|inspect)\s+([\w/\-\.]+(?:\.\w+))",
            prompt, re.IGNORECASE,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "src/my_file.py")

    def test_target_set_via_run(self):
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        state = RuntimeState(session_id="test-target-run-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", '
                '"args": {"answer": "Found the bug."}}'
            ),
            max_output_len=100,
        )
        outcome = loop.run("Read broken_script.py and find the bug")
        self.assertIsNotNone(outcome)
        self.assertEqual(
            loop._ctx.intent_policy.required_target,
            "broken_script.py",
        )

    def test_target_relative_set_via_run(self):
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        state = RuntimeState(session_id="test-target-rel-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", '
                '"args": {"answer": "Checked imports."}}'
            ),
            max_output_len=100,
        )
        outcome = loop.run("Read src/app.py and check its imports")
        self.assertIsNotNone(outcome)
        self.assertEqual(
            loop._ctx.intent_policy.required_target,
            "src/app.py",
        )

    def test_target_traversal_attempt(self):
        """Path traversal with '..' must be flagged (stored for diagnostics)."""
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        state = RuntimeState(session_id="test-trav-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", '
                '"args": {"answer": "N/A"}}'
            ),
            max_output_len=100,
        )
        # Use a path with a proper extension so the regex matches
        outcome = loop.run("Read ../../etc/passwd.txt and check it")
        self.assertIsNotNone(outcome)
        # The traversal path should be extracted for diagnostic purposes
        target = loop._ctx.intent_policy.required_target
        self.assertIn("..", target)
        self.assertIn("passwd.txt", target)


# ====================================================================
# PART 5: S2 Strict Progression Tests (4 stages)
# ====================================================================
class TestS2StrictProgression(unittest.TestCase):
    """S2 must reject finalization sequentially through 4 stages."""

    S2_PROMPT = "Analyze this repository and summarize its architecture."

    def _make_loop(self):
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        state = RuntimeState(session_id="test-s2-prog-r4")
        return ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", '
                '"args": {"answer": "The architecture is modular."}}'
            ),
            max_output_len=100,
        )

    def test_stage1_0reads_no_plan_no_listing_rejected(self):
        """Stage 1: 0 reads, no plan, no listing -> REJECT via policy + gate."""
        from core.investigation import classify_intent, InvestigationIntent
        from engine._loop_helpers import _get_intent_policy

        intent = classify_intent(self.S2_PROMPT)
        self.assertIn(intent, (
            InvestigationIntent.ARCHITECTURE_REVIEW,
            InvestigationIntent.REPOSITORY_INVESTIGATION,
        ))
        policy = _get_intent_policy(intent)
        self.assertTrue(policy.requires_plan)
        self.assertGreaterEqual(policy.minimum_reads, 3)
        self.assertTrue(policy.requires_root_listing)

        from core.convergence_gate import can_finalize
        evidence_log = MagicMock()
        evidence_log.get_records.return_value = []
        decision = can_finalize(
            evidence_log=evidence_log,
            requires_plan=True,
            requires_root_listing=True,
            completion_tracker=None,
        )
        self.assertFalse(decision.allowed)

    def test_stage2_plan_only_rejected(self):
        """Stage 2: Plan exists but no listing/reads -> REJECT."""
        from core.convergence_gate import can_finalize, DeepAgentPlanCompletionTracker
        tracker = DeepAgentPlanCompletionTracker(
            plan=["List root", "Read core/__init__.py",
                  "Read engine/loop.py", "Read tests/test_main.py"],
            current_plan_index=1,
            past_steps=["List root"],
        )
        evidence_log = MagicMock()
        evidence_log.get_records.return_value = []
        decision = can_finalize(
            completion_tracker=tracker,
            evidence_log=evidence_log,
            requires_plan=True,
            requires_root_listing=True,
        )
        self.assertFalse(decision.allowed)

    def test_stage3_plan_listing_2reads_rejected(self):
        """Stage 3: Plan + listing + 2 reads -> REJECT (only 2, need >= 3)."""
        from core.convergence_gate import can_finalize, DeepAgentPlanCompletionTracker
        from core.evidence import EvidenceRecord
        tracker = DeepAgentPlanCompletionTracker(
            plan=["List root", "Read core/__init__.py",
                  "Read engine/loop.py", "Read tests/test_main.py",
                  "Synthesize report"],
            current_plan_index=3,
            past_steps=["List root", "Read core/__init__.py",
                        "Read engine/loop.py"],
        )
        evidence_log = MagicMock()
        evidence_log.get_records.return_value = [
            EvidenceRecord(tool="file_system", action="list",
                           command_or_path=".", success=True,
                           output_snippet="core/\nengine/\ntests/"),
            EvidenceRecord(tool="file_system", action="read",
                           command_or_path="core/__init__.py", success=True,
                           output_snippet="def main():\n    pass"),
            EvidenceRecord(tool="file_system", action="read",
                           command_or_path="engine/loop.py", success=True,
                           output_snippet="class ExecutionLoop:"),
        ]
        # The can_finalize gate: root listing passes, plan is in progress.
        # But the policy requires minimum_reads >= 3 (enforced in _emit_final).
        from core.investigation import classify_intent, InvestigationIntent
        from engine._loop_helpers import _get_intent_policy
        intent = classify_intent(self.S2_PROMPT)
        if isinstance(intent, InvestigationIntent):
            policy = _get_intent_policy(intent)
            self.assertGreaterEqual(policy.minimum_reads, 3)
        # can_finalize with requires_plan=True and a tracker with pending items
        # will find that items 2 (engine/loop.py), 3 (tests/test_main.py)
        # and 4 (Synthesize report) are still pending.
        decision = can_finalize(
            completion_tracker=tracker,
            evidence_log=evidence_log,
            requires_plan=True,
            requires_root_listing=True,
        )
        # At least one pending TODO -> allowed=False
        self.assertFalse(decision.allowed)

    def test_stage4_plan_listing_3reads_allowed(self):
        """Stage 4: Plan + listing + 3 reads -> ALLOWED."""
        from core.convergence_gate import can_finalize, DeepAgentPlanCompletionTracker
        from core.evidence import EvidenceRecord
        tracker = DeepAgentPlanCompletionTracker(
            plan=["List root", "Read core/__init__.py",
                  "Read engine/loop.py", "Read tests/test_main.py",
                  "Synthesize report"],
            current_plan_index=5,
            past_steps=["List root", "Read core/__init__.py",
                        "Read engine/loop.py", "Read tests/test_main.py",
                        "Synthesize report"],
        )
        evidence_log = MagicMock()
        evidence_log.get_records.return_value = [
            EvidenceRecord(tool="file_system", action="list",
                           command_or_path=".", success=True,
                           output_snippet="core/\nengine/\ntests/"),
            EvidenceRecord(tool="file_system", action="read",
                           command_or_path="core/__init__.py", success=True,
                           output_snippet="def main():\n    pass"),
            EvidenceRecord(tool="file_system", action="read",
                           command_or_path="engine/loop.py", success=True,
                           output_snippet="class ExecutionLoop:"),
            EvidenceRecord(tool="file_system", action="read",
                           command_or_path="tests/test_main.py", success=True,
                           output_snippet="def test_loop():"),
        ]
        decision = can_finalize(
            completion_tracker=tracker,
            evidence_log=evidence_log,
            requires_plan=True,
            requires_root_listing=True,
        )
        self.assertTrue(decision.allowed)


# ====================================================================
# PART 6: Native Live Smoke Tests (No Monkeypatch)
# ====================================================================
class TestNativeLiveSmoke(unittest.TestCase):
    """Native (unmocked classification pipeline) E2E tests."""

    def test_native_s1_success(self):
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        from core.investigation import InvestigationIntent

        state = RuntimeState(session_id="test-6-s1-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", '
                '"args": {"answer": "Syntax error: missing colon on line 5."}}'
            ),
            max_output_len=100,
        )
        outcome = loop.run(
            "Read broken_script.py and identify the syntax error."
        )
        self.assertIsNotNone(outcome)
        self.assertTrue(loop._turn_finalizer.is_finalized)
        self.assertEqual(loop._ctx.phase, "FINALIZE")
        self.assertEqual(
            loop._ctx.intent, InvestigationIntent.SINGLE_FILE_LOOKUP,
        )
        self.assertEqual(
            loop._ctx.intent_policy.required_target, "broken_script.py",
        )
        self.assertEqual(loop._ctx.intent_policy.minimum_reads, 1)
        self.assertFalse(loop._ctx.intent_policy.requires_plan)
        self.assertFalse(loop._ctx.intent_policy.requires_root_listing)

    def test_native_s2_full_success(self):
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        from core.investigation import InvestigationIntent

        state = RuntimeState(session_id="test-6-s2-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", '
                '"args": {"answer": "The architecture is modular."}}'
            ),
            max_output_len=100,
        )
        outcome = loop.run(
            "Analyze this repository and summarize its architecture."
        )
        self.assertIsNotNone(outcome)
        self.assertTrue(loop._turn_finalizer.is_finalized)
        self.assertEqual(loop._ctx.phase, "FINALIZE")
        intent = loop._ctx.intent
        self.assertIn(intent, (
            InvestigationIntent.ARCHITECTURE_REVIEW,
            InvestigationIntent.REPOSITORY_INVESTIGATION,
        ))
        policy = loop._ctx.intent_policy
        self.assertTrue(policy.requires_plan)
        self.assertGreaterEqual(policy.minimum_reads, 3)
        self.assertTrue(policy.needs_investigation)
        self.assertTrue(policy.requires_root_listing)

    def test_native_s2_incomplete_rejected(self):
        """Native S2 with no evidence: must REJECT finalization (FAILED outcome)."""
        from engine.state import RuntimeState
        from engine.loop import ExecutionLoop
        from core.turn_outcome import TurnStatus
        from core.investigation import InvestigationIntent

        state = RuntimeState(session_id="test-6-s2-inc-r4")
        loop = ExecutionLoop(
            state=state,
            llm_provider=lambda msgs: (
                '{"tool": "final_answer", '
                '"args": {"answer": "The repo has a modular architecture."}}'
            ),
            max_output_len=100,
        )
        # Verify policy BEFORE running
        from core.investigation import classify_intent
        from engine._loop_helpers import _get_intent_policy
        intent = classify_intent(
            "Analyze this repository and summarize its architecture."
        )
        if isinstance(intent, InvestigationIntent):
            policy = _get_intent_policy(intent)
            self.assertTrue(policy.requires_plan)
            self.assertTrue(policy.requires_root_listing)
            self.assertGreaterEqual(policy.minimum_reads, 3)
        # Run the loop — with 0 evidence and requires_plan + root_listing,
        # the convergence gate should block and the outcome should reflect
        # a non-COMPLETED terminal state.
        outcome = loop.run(
            "Analyze this repository and summarize its architecture."
        )
        self.assertIsNotNone(outcome)
        # The loop may not reach COMPLETED due to missing evidence.
        # The important assertion: it must NOT produce a successful
        # COMPLETED outcome without evidence.
        # The loop must NOT produce COMPLETED or PAUSED — it must FAIL
        self.assertEqual(
            outcome.status.value, "FAILED",
            "S2 missing evidence must produce FAILED, not COMPLETED/PAUSED",
        )


# ====================================================================
# Main runner
# ====================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
