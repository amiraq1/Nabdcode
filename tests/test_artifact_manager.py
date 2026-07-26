"""Unit and integration tests for ArtifactManager and its wiring into UnifiedStorage/AppContext."""

import os
import time
from pathlib import Path
import pytest
from core.artifact_manager import ArtifactManager
from core.storage import UnifiedStorage
from core.app_context import AppContext


def test_artifact_lifecycle(tmp_path: Path):
    mgr = ArtifactManager(root_dir=tmp_path)
    
    # 1. Create artifact
    content = "Hello, NABD OS Artifacts!\nLine 2\nLine 3"
    record = mgr.create_artifact(
        name="test_report.md",
        content=content,
        category="report",
        metadata={"author": "Architect"},
    )
    assert record["artifact_id"].startswith("art_")
    assert record["size_bytes"] == len(content)
    assert record["category"] == "report"
    assert "data/" in record["relative_path"]
    
    # 2. Get by ID and by exact name
    art_by_id = mgr.get_artifact(record["artifact_id"])
    assert art_by_id == content
    
    art_by_name = mgr.get_artifact("test_report.md")
    assert art_by_name == content
    
    # 3. List and filter
    mgr.create_artifact(name="scratch.py", content="print(1)", category="scratch")
    reports = mgr.list_artifacts(category="report")
    assert len(reports) == 1
    assert reports[0]["name"] == "test_report.md"
    
    all_arts = mgr.list_artifacts()
    assert len(all_arts) == 2
    
    # 4. Delete
    assert mgr.delete_artifact(record["artifact_id"]) is True
    assert mgr.get_artifact(record["artifact_id"]) is None
    assert not Path(record["absolute_path"]).exists()


def test_offload_tool_output(tmp_path: Path):
    mgr = ArtifactManager(root_dir=tmp_path, max_inline_chars=100)
    
    # 1. Short output (under threshold) returns unchanged, no artifact created
    short_text = "Short tool output"
    res_text, res_rec = mgr.offload_tool_output("ShellTool", short_text)
    assert res_text == short_text
    assert res_rec is None
    assert len(mgr.list_artifacts()) == 0
    
    # 2. Long output (over threshold) offloads to disk and returns summary preview
    long_text = "A" * 500
    res_text, res_rec = mgr.offload_tool_output("ShellTool", long_text)
    assert res_rec is not None
    assert res_rec["category"] == "offload"
    assert "[Tool Output Offloaded to Artifact]" in res_text
    assert res_rec["artifact_id"] in res_text
    assert mgr.get_artifact(res_rec["artifact_id"]) == long_text


def test_pruning_caps(tmp_path: Path):
    # Set tight byte cap: 200 bytes
    mgr = ArtifactManager(root_dir=tmp_path, max_total_bytes=200)
    
    r1 = mgr.create_artifact("file1.txt", "X" * 120, category="test")
    time.sleep(0.01)
    r2 = mgr.create_artifact("file2.txt", "Y" * 120, category="test")
    
    # Total would be 240 > 200 bytes, so oldest (r1) should be pruned immediately
    all_arts = mgr.list_artifacts()
    assert len(all_arts) == 1
    assert all_arts[0]["artifact_id"] == r2["artifact_id"]
    assert not (mgr.data_dir / f"{r1['artifact_id']}_file1_txt").exists()


def test_storage_and_app_context_wiring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NABD_ROOT_DIR", str(tmp_path))
    monkeypatch.setenv("NABD_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NABD_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("NABD_LOG_DIR", str(tmp_path / "logs"))
    
    storage = UnifiedStorage(root_dir=tmp_path)
    assert storage.artifact_manager is not None
    assert isinstance(storage.artifact_manager, ArtifactManager)
    
    ctx = AppContext.build()
    assert ctx.artifact_manager is not None
    assert isinstance(ctx.artifact_manager, ArtifactManager)
    
    # Verify persistence via ctx
    rec = ctx.artifact_manager.create_artifact("system_check.log", "OK")
    assert ctx.artifact_manager.get_artifact(rec["artifact_id"]) == "OK"
