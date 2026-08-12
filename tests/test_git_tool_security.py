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


def test_git_tool_exists():
    tool = GitTool()
    assert callable(tool.execute)


def test_allowed_commands():
    tool = GitTool()
    assert "log" in tool.ALLOWED
    assert "diff" in tool.ALLOWED
    assert "status" in tool.ALLOWED
    assert "show" in tool.ALLOWED
    assert "branch" in tool.ALLOWED
    assert "tag" in tool.ALLOWED
    assert "commit" not in tool.ALLOWED


def test_forbidden_commands():
    tool = GitTool()
    res = tool.execute("clean -fd")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert "forbidden" in res.stderr
    res = tool.execute("push origin main")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert "forbidden" in res.stderr


def test_not_allowed_commands():
    tool = GitTool()
    res = tool.execute("rebase -i HEAD~3")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert "not allowed" in res.stderr


def test_safe_execution(monkeypatch):
    tool = GitTool()
    _patch_git_run(monkeypatch, stdout="commit1\ncommit2\ncommit3\ncommit4\ncommit5")
    res = tool.execute("log --oneline -5")
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert "commit" in res.stdout


def test_no_shell_injection(monkeypatch):
    tool = GitTool()
    # shell=False: metacharacters become literal git args, never a shell.
    _patch_git_run(monkeypatch, stdout="safe")
    res = tool.execute("log -n 3; echo hacked")
    assert isinstance(res, ToolResult)
    assert res.success is True
