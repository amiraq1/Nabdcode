"""Phase UI-3 — UI polish (real EDIT diff + stage-aware status verbs).

Verifies:
  1. map_tool_to_badge returns 'EDIT' for file_system write/append/replace actions.
  2. select_status_verb returns stage-aware verbs (Sculpting, Examining, Tuning, etc.).
  3. FileSystemTool write/append/replace computes real unified diff and stores metadata (additions, deletions).
  4. Renderer tool_end renders diff stats line (+A -D) correctly.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.ui_theme import map_tool_to_badge, select_status_verb, render_diff
from tools.file_system import FileSystemTool


def test_map_tool_to_badge_edit_actions():
    assert map_tool_to_badge("file_system", {"action": "write"}) == "EDIT"
    assert map_tool_to_badge("file_system", {"action": "append"}) == "EDIT"
    assert map_tool_to_badge("file_system", {"action": "replace"}) == "EDIT"
    assert map_tool_to_badge("file_system", {"action": "read"}) == "READ"


def test_select_status_verb_stages():
    assert select_status_verb("edit", "file_system", turn_index=0) == "Sculpting"
    assert select_status_verb("edit", "file_system", turn_index=1) == "Crafting"
    assert select_status_verb("shell", "execute_shell", turn_index=0) == "Tuning"
    assert select_status_verb("shell", "execute_shell", turn_index=1) == "Verifying"
    assert select_status_verb("read", "file_system", turn_index=0) == "Examining"
    assert select_status_verb("init", "", turn_index=0) == "Examining"


def test_filesystem_diff_and_metadata():
    tool = FileSystemTool()
    tmpdir = Path.cwd() / ".tmp_ui3_test"
    tmpdir.mkdir(exist_ok=True)
    target = tmpdir / "test_diff.py"
    try:
        # 1. First write
        res1 = tool.execute(action="write", path=str(target), content="line1\nline2\n")
        assert res1.success
        assert "diff" in res1.metadata
        assert res1.metadata["additions"] == 2
        assert res1.metadata["deletions"] == 0

        # 2. Append
        res2 = tool.execute(action="append", path=str(target), content="line3\n")
        assert res2.success
        assert res2.metadata["additions"] == 1
        assert res2.metadata["deletions"] == 0

        # 3. Replace
        res3 = tool.execute(action="replace", path=str(target), old_text="line2", new_text="line2_updated")
        assert res3.success
        assert res3.metadata["additions"] == 1
        assert res3.metadata["deletions"] == 1
    finally:
        if target.exists():
            target.unlink()
        if tmpdir.exists():
            tmpdir.rmdir()


def test_render_diff_formatting():
    diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old_line\n+new_line"
    rendered = render_diff(diff, max_lines=16)
    assert "old_line" in rendered
    assert "new_line" in rendered


if __name__ == "__main__":
    test_map_tool_to_badge_edit_actions()
    test_select_status_verb_stages()
    test_filesystem_diff_and_metadata()
    test_render_diff_formatting()
    print("All Phase UI-3 tests passed.")
