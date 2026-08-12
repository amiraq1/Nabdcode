import subprocess

from tools.git_tool import GitTool
from tools.models import ToolResult


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


def test_write_requires_consent():
    tool = GitTool()
    res = tool.execute("add .")
    assert isinstance(res, ToolResult)
    assert res.status == "consent_required"
    assert res.metadata.get("command") == "add ."
    assert "preview" in res.metadata


def test_consent_approved_executes(monkeypatch):
    # Simulate force_execute=True (set by the engine after user approval).
    tool = GitTool()
    _patch_git_run(monkeypatch, stdout="success")
    res = tool.execute("commit -m 'test'", force_execute=True)
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert "success" in res.stdout


def test_consent_denied_aborts():
    # If a user denies in loop.py, it doesn't call tool again.
    # But if the engine intercepts, we can test that logic later.
    pass


def test_dangerous_commands_blocked():
    tool = GitTool()
    res = tool.execute("push origin main")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert "forbidden" in res.stderr
    res = tool.execute("reset --hard")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert "forbidden" in res.stderr


def test_anchors_alive(monkeypatch):
    tool = GitTool()
    _patch_git_run(monkeypatch, stdout="log")
    res = tool.execute("log -n 3")
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert "log" in res.stdout
