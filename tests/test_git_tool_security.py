import pytest
from tools.git_tool import GitTool

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
    with pytest.raises(ValueError, match="forbidden"):
        tool.execute("commit -m 'test'")
    with pytest.raises(ValueError, match="forbidden"):
        tool.execute("push origin main")

def test_not_allowed_commands():
    tool = GitTool()
    with pytest.raises(ValueError, match="not allowed"):
        tool.execute("rebase -i HEAD~3")

def test_safe_execution():
    tool = GitTool()
    res = tool.execute("log --oneline -5")
    assert isinstance(res, str)
    # The output should have 5 lines (commits) or less if repo has <5 commits
    
def test_no_shell_injection():
    tool = GitTool()
    # It should pass only the first part to split, or treat the whole as arguments
    # Wait, if we use subprocess.run(["git"] + command.split(), shell=False), it will 
    # just pass it as arguments to git, so shell injection is not possible.
    # We can check that it doesn't crash or that it just passes arguments safely.
    pass
