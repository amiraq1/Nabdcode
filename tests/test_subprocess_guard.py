"""tests/test_subprocess_guard.py — Unit verification for the centralized SubprocessGuard.

Covers: agent-shell validation + consent, git policy, infra policy, and
uniform error containment.  These are the success / failure / edge paths
required by the P0.1 remediation.
"""

from __future__ import annotations

import unittest

from core.kernel.subprocess_guard import SubprocessGuard, Policy, default_guard


class TestSubprocessGuardAgentShell(unittest.TestCase):
    """AGENT_SHELL policy: validate() gate + consent seam."""

    def test_safe_command_executes(self):
        guard = SubprocessGuard()
        code, out, err = guard.run_agent_command("echo hello", timeout=5)
        self.assertEqual(code, 0)
        self.assertIn("hello", out)

    def test_dangerous_command_blocked(self):
        # `rm` is not whitelisted by the kernel security engine.
        guard = SubprocessGuard()
        code, out, err = guard.run_agent_command("rm -rf /", timeout=5)
        self.assertEqual(code, -1)
        self.assertIn("Security Violation", err)

    def test_consent_callback_can_block(self):
        guard = SubprocessGuard(consent_callback=lambda name, args: False)
        code, out, err = guard.run_agent_command("echo hi", timeout=5, tool_name="execute_shell")
        self.assertEqual(code, -1)
        self.assertIn("blocked by user", err.lower())

    def test_consent_callback_can_approve(self):
        guard = SubprocessGuard(consent_callback=lambda name, args: True)
        code, out, err = guard.run_agent_command("echo approved", timeout=5)
        self.assertEqual(code, 0)
        self.assertIn("approved", out)


class TestSubprocessGuardGit(unittest.TestCase):
    """GIT policy: tokenized allowlist, workspace containment."""

    def test_git_push_records_evidence(self):
        # Run against the real guard (git push will fail gracefully outside a
        # repo, but the function must record both EvidenceRecords without crashing).
        from tools.git_tool import push_and_verify_evidence
        import core.evidence as ev_mod

        log = ev_mod.EvidenceLog()
        recs = push_and_verify_evidence(log, remote="origin", branch="main")
        self.assertIn("push_record", recs)
        self.assertIn("diff_record", recs)
        self.assertEqual(len(log._records), 2)


class TestSubprocessGuardInfra(unittest.TestCase):
    """INFRA policy: internal process spawning, no user validation."""

    def test_infra_runs_and_returns_tuple(self):
        guard = SubprocessGuard()
        result = guard.run_infra(["python3", "-c", "print('infra-ok')"], timeout=10)
        self.assertEqual(result[0], 0)
        self.assertIn("infra-ok", result[1])

    def test_infra_missing_binary_returns_error_tuple(self):
        guard = SubprocessGuard()
        result = guard.run_infra(["this_binary_does_not_exist_xyz"], timeout=5)
        self.assertEqual(result[0], -1)
        self.assertIn("not found", result[2])

    def test_infra_timeout_contained(self):
        guard = SubprocessGuard()
        result = guard.run_infra(["python3", "-c", "import time; time.sleep(5)"], timeout=0.3)
        self.assertEqual(result[0], -1)
        self.assertIn("timed out", result[2])


class TestSubprocessGuardSpawn(unittest.TestCase):
    """INFRA long-lived spawn: returns Popen or None on failure."""

    def test_spawn_infra_returns_handle(self):
        guard = SubprocessGuard()
        proc = guard.spawn_infra(["python3", "-c", "import time; time.sleep(2)"])
        self.assertIsNotNone(proc)
        proc.kill()
        proc.wait()

    def test_spawn_infra_missing_binary_returns_none(self):
        guard = SubprocessGuard()
        proc = guard.spawn_infra(["missing_binary_xyz"])
        self.assertIsNone(proc)


class TestSubprocessGuardPolicy(unittest.TestCase):
    """Policy enum sanity."""

    def test_policy_values(self):
        self.assertEqual(Policy.AGENT_SHELL.value, "agent_shell")
        self.assertEqual(Policy.GIT.value, "git")
        self.assertEqual(Policy.INFRA.value, "infra")


if __name__ == "__main__":
    unittest.main()
