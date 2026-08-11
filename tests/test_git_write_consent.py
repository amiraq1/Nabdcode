import pytest
import subprocess
from tools.git_tool import GitTool

def test_write_requires_consent():
    tool = GitTool()
    res = tool.execute("add .")
    assert isinstance(res, dict)
    assert res.get("status") == "consent_required"
    assert res.get("command") == "add ."
    assert "preview" in res

def test_consent_approved_executes(monkeypatch):
    # Simulate force_execute=True
    tool = GitTool()
    # Mock subprocess.run
    def mock_run(*args, **kwargs):
        class MockResult:
            stdout = "success"
            stderr = ""
            returncode = 0
        return MockResult()
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    res = tool.execute("commit -m 'test'", force_execute=True)
    assert res == "success"

def test_consent_denied_aborts():
    # If a user denies in loop.py, it doesn't call tool again. 
    # But if the engine intercepts, we can test that logic later.
    pass

def test_dangerous_commands_blocked():
    tool = GitTool()
    with pytest.raises(ValueError, match="Forbidden|forbidden"):
        tool.execute("push origin main")
    with pytest.raises(ValueError, match="Forbidden|forbidden"):
        tool.execute("reset --hard")
        
def test_anchors_alive(monkeypatch):
    tool = GitTool()
    def mock_run(*args, **kwargs):
        class MockResult:
            stdout = "log"
            stderr = ""
            returncode = 0
        return MockResult()
    monkeypatch.setattr(subprocess, "run", mock_run)
    res = tool.execute("log -n 3")
    assert res == "log"
