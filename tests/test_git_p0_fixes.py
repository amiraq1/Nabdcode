"""GIT-P0 — Red/green tests for the critical git_tool security fixes (Am+18).

Covers:
  ع1 consent_loop_broken_before_fix — write commands must surface consent
  ع2 consent_loop_fixed_after       — force_execute actually executes
  ع3 git_push_requires_consent      — git_push in _CONSENT_REQUIRED_TOOLS
  ع4 output_flag_blocked            — --output smuggled into read commands
  ع5 git_tool_returns_toolresult    — typed ToolResult, never str/dict
  ع6 anchors_alive                  — constitutional fingerprints unchanged
"""

import hashlib
import subprocess
from pathlib import Path

from tools.git_tool import GitTool
from tools.models import ToolResult
from engine.consent import _CONSENT_REQUIRED_TOOLS

ROOT = Path(__file__).resolve().parents[1]

# Constitutional fingerprints — any change here is a hard HALT.
FINGERPRINTS = {
    "ui/widgets/status_bar.py": "e5e5e3d5089915bc",
    "tests/test_the_bar_hears_the_bus.py": "b9273177d096e78a",
    "tests/test_the_bar_clock_turns.py": "8bbc623c388d4f02",
}


class _FakeGitResult:
    def __init__(self, stdout="ok", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch_git_run(monkeypatch, stdout="ok", stderr="", returncode=0):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeGitResult(stdout=stdout, stderr=stderr, returncode=returncode),
    )


# ع1: without approval, a write command must NOT execute — it surfaces consent.
def test_consent_loop_broken_before_fix():
    tool = GitTool()
    res = tool.execute(command="git add .")
    assert isinstance(res, ToolResult)
    assert res.status == "consent_required"
    assert res.metadata.get("command") == "git add ."


# ع2: after user approval (force_execute=True) the write command actually runs.
def test_consent_loop_fixed_after(monkeypatch):
    tool = GitTool()
    _patch_git_run(monkeypatch, stdout="staged")
    res = tool.execute(command="git add .", force_execute=True)
    assert isinstance(res, ToolResult)
    assert res.status == "success"
    assert "staged" in res.stdout


# ع3: git_push requires human consent at the engine gate.
def test_git_push_requires_consent():
    assert "git_push" in _CONSENT_REQUIRED_TOOLS


# ع4: --output (file-write primitive) is blocked in "read-only" commands.
def test_output_flag_blocked():
    tool = GitTool()
    res = tool.execute(command="git diff --output=/tmp/evil.txt")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert "--output" in res.stderr


# ع4b: the short form -o (alias of --output) is blocked too.
def test_output_short_flag_blocked():
    tool = GitTool()
    res = tool.execute(command="git diff -o /tmp/evil.txt")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert "-o" in res.stderr


# ع5: read commands return a typed ToolResult (never str or dict).
def test_git_tool_returns_toolresult(monkeypatch):
    tool = GitTool()
    _patch_git_run(monkeypatch, stdout="abc123")
    res = tool.execute(command="log -n 1")
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert "abc123" in res.stdout


# ع6: constitutional anchors remain untouched.
def test_anchors_alive():
    for rel, prefix in FINGERPRINTS.items():
        p = ROOT / rel
        assert p.is_file(), f"constitutional file missing: {rel}"
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        assert digest == prefix, f"fingerprint changed for {rel}: {digest}"
