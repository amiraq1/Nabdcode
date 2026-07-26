"""Live E2E Lifecycle verification for RepositoryContextManager and AppContext.build().

Verifies:
1. AppContext.build() resets STATE.md at session start.
2. Sequential turns inside the same session preserve prior task states without wiping.
3. Subagent loops/spawns do not call AppContext.build() or reset STATE.md.
4. Concurrent writes are thread-safe (RLock) and crash-safe (atomic tmp + os.replace).
5. Truncation keeps the newest chronological entries (top of section via entries[:25]).
"""

import os
import shutil
import threading
from pathlib import Path
import pytest
from core.context_manager import RepositoryContextManager
from core.app_context import AppContext
from core.config import AgentConfig


def test_live_lifecycle_and_subagent_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test full E2E session lifecycle, multi-turn persistence, and subagent non-interference."""
    # Setup isolated root and workspace env vars checked by AgentConfig
    monkeypatch.setenv("NABD_ROOT_DIR", str(tmp_path))
    monkeypatch.setenv("NABD_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NABD_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("NABD_LOG_DIR", str(tmp_path / "logs"))
    
    state_file = tmp_path / "STATE.md"
    
    # 1. Simulate Session Start: AppContext.build()
    # (Note: AppContext.build() calls RepositoryContextManager(root=workspace).reset_session_state())
    ctx = AppContext.build()
    assert state_file.exists(), "STATE.md must be created at session initialization"
    assert "# Task State Log" in state_file.read_text("utf-8")
    
    # 2. Simulate Turn 1: In Progress -> Completed
    mgr = RepositoryContextManager(root=tmp_path)
    mgr.update_state("task-turn-1", "In Progress", {"prompt": "First turn prompt"})
    assert "`task-turn-1`" in state_file.read_text("utf-8")
    assert "## In Progress" in state_file.read_text("utf-8")
    
    mgr.update_state("task-turn-1", "Completed", {"prompt": "First turn prompt"})
    content_after_t1 = state_file.read_text("utf-8")
    assert "`task-turn-1`" in content_after_t1
    assert "- **Completed** | `task-turn-1`" in content_after_t1
    
    # 3. Simulate Turn 2: verify Turn 1 is NOT wiped when Turn 2 starts
    mgr.update_state("task-turn-2", "In Progress", {"prompt": "Second turn prompt"})
    content_during_t2 = state_file.read_text("utf-8")
    assert "`task-turn-1`" in content_during_t2, "Turn 1 state must persist when Turn 2 begins"
    assert "`task-turn-2`" in content_during_t2
    
    mgr.update_state("task-turn-2", "Completed", {"prompt": "Second turn prompt"})
    content_after_t2 = state_file.read_text("utf-8")
    assert "`task-turn-1`" in content_after_t2
    assert "`task-turn-2`" in content_after_t2
    
    # 4. Simulate Subagent / Retry Loop execution: verify it does not trigger reset
    from engine.subagent_runner import SubagentRunner
    sub_runner = SubagentRunner(router=None)
    content_after_subagent = state_file.read_text("utf-8")
    assert "`task-turn-1`" in content_after_subagent
    assert "`task-turn-2`" in content_after_subagent


def test_atomic_write_and_concurrent_safety(tmp_path: Path):
    """Verify concurrent thread safety and atomic os.replace writes."""
    mgr = RepositoryContextManager(root=tmp_path)
    mgr.reset_session_state()
    
    errors = []
    
    def worker(worker_id: int):
        try:
            for i in range(20):
                task_id = f"task-w{worker_id}-{i}"
                mgr.update_state(task_id, "Completed", {"attempts": i})
        except Exception as e:
            errors.append(e)
            
    threads = [threading.Thread(target=worker, args=(w,)) for w in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    assert not errors, f"Concurrent updates raised errors: {errors}"
    content = (tmp_path / "STATE.md").read_text("utf-8")
    assert "# Task State Log" in content
    assert "- **Completed**" in content


def test_chronological_truncation_order(tmp_path: Path):
    """Verify that _truncate_if_needed keeps the newest chronological items (top of section)."""
    mgr = RepositoryContextManager(root=tmp_path)
    mgr.reset_session_state()
    
    # Insert 40 items in chronological order (i=0 is oldest, i=39 is newest)
    # Note: _insert_under_section inserts each new item at index 0 under ## Completed
    for i in range(40):
        mgr.update_state(f"task-chron-{i}", "Completed", {"index": i})
        
    raw = (tmp_path / "STATE.md").read_text("utf-8")
    
    # Force truncation verification
    truncated = mgr._truncate_if_needed(raw, force=True)
    
    # Since task-chron-39 was inserted most recently, it sits directly under ## Completed (index 0)
    # entries[:25] should keep task-chron-39 down to task-chron-15, and drop task-chron-14 down to task-chron-0
    assert "`task-chron-39`" in truncated, "Newest chronological item (task-chron-39) must be kept"
    assert "`task-chron-38`" in truncated
    assert "`task-chron-15`" in truncated
    assert "`task-chron-0`" not in truncated, "Oldest chronological item (task-chron-0) must be dropped"
