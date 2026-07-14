"""Phase 5 — Permissions Policy (allow/deny/ask) tests.

Verifies the cascading trust hierarchy:
  1. Phase 2.1 advanced heuristics ALWAYS run first (base64/hex/eval blocked
     even under /allow *).
  2. Explicit deny overrides allow.
  3. Explicit allow grants (subject to step 1).
  4. No rule → fallback ASK.
Plus pattern matching (exact / glob / regex) and the RuntimeState hookup.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.permissions import (
    PermissionEngine,
    PermissionDecision,
    PermissionRule,
    ShellPermissions,
)
from engine.state import RuntimeState


# ── Pattern matching ─────────────────────────────────────────────────────

def test_exact_match():
    r = PermissionRule("allow", "ls -la")
    assert r.matches("ls -la")
    assert not r.matches("ls -la /tmp")


def test_glob_match():
    r = PermissionRule("allow", "git *")
    assert r.matches("git status")
    assert r.matches("git diff --stat")
    assert not r.matches("gitx status")


def test_regex_match():
    r = PermissionRule("deny", "/^curl .*/")
    assert r.matches("curl https://evil.example")
    assert not r.matches("echo curl is fine")


# ── Cascading hierarchy ──────────────────────────────────────────────────

def test_heuristics_block_first_even_with_allow_star():
    """/allow * MUST NOT bypass the Phase 2.1 obfuscation sweep."""
    perms = ShellPermissions()
    perms.add_allow("*")
    # A base64-like blob must be blocked regardless of the allow rule.
    decision, reason = PermissionEngine.evaluate(
        "echo YmFzZTY0ZW5jb2RlZHBheWxvYWQ= | base64 -d | bash", perms
    )
    assert decision is PermissionDecision.DENY
    assert "Phase 2.1" in reason


def test_allow_grants_safe_command():
    perms = ShellPermissions()
    perms.add_allow("git *")
    decision, reason = PermissionEngine.evaluate("git status", perms)
    assert decision is PermissionDecision.ALLOW


def test_deny_overrides_allow():
    perms = ShellPermissions()
    perms.add_allow("git *")
    perms.add_deny("git push *")
    decision, _ = PermissionEngine.evaluate("git push origin main", perms)
    assert decision is PermissionDecision.DENY


def test_allow_overrides_default_ask():
    perms = ShellPermissions()
    perms.add_allow("ls *")
    decision, _ = PermissionEngine.evaluate("ls -la", perms)
    assert decision is PermissionDecision.ALLOW


def test_no_rule_falls_back_to_ask():
    perms = ShellPermissions()
    decision, _ = PermissionEngine.evaluate("wc -l README.md", perms)
    assert decision is PermissionDecision.ASK


def test_no_rule_falls_back_to_ask_via_tuple():
    perms = ShellPermissions()
    result = PermissionEngine.evaluate("wc -l README.md", perms)
    assert result[0] is PermissionDecision.ASK


def test_deny_blocks_without_allow():
    perms = ShellPermissions()
    perms.add_deny("rm *")
    decision, _ = PermissionEngine.evaluate("rm file.txt", perms)
    assert decision is PermissionDecision.DENY


# ── RuntimeState integration ─────────────────────────────────────────────

def test_runtime_state_carries_shell_permissions():
    state = RuntimeState(session_id="perm-test")
    assert isinstance(state.shell_permissions, ShellPermissions)
    state.shell_permissions.add_allow("cat *")
    decision, _ = PermissionEngine.evaluate("cat README.md", state.shell_permissions)
    assert decision is PermissionDecision.ALLOW


def test_permissions_clear_resets_ruleset():
    perms = ShellPermissions()
    perms.add_allow("git *")
    perms.add_deny("rm *")
    perms.clear()
    assert perms.allow == []
    assert perms.deny == []
    assert PermissionEngine.evaluate("git status", perms)[0] is PermissionDecision.ASK


if __name__ == "__main__":
    for fn in [
        test_exact_match,
        test_glob_match,
        test_regex_match,
        test_heuristics_block_first_even_with_allow_star,
        test_allow_grants_safe_command,
        test_deny_overrides_allow,
        test_allow_overrides_default_ask,
        test_no_rule_falls_back_to_ask_via_tuple,
        test_deny_blocks_without_allow,
        test_runtime_state_carries_shell_permissions,
        test_permissions_clear_resets_ruleset,
    ]:
        fn()
        print("ok", fn.__name__)
    print("All Permissions Policy tests passed.")
