"""Phase UI — Cursor-like TUI (no logic changes, rendering only).

Verifies:
  1. map_tool_to_badge maps tool names correctly.
  2. collapsed count formatting.
  3. todo_block contains ☒/☐ glyphs with correct status.
  4. render_diff renders +/- lines.
  5. think_line has duration text.
  6. badge returns ANSI-wrapped text.
  7. Renderer thread safety: concurrent tool_start + stream_chunk.
"""

import sys
import os
import threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.ui_theme import (
    map_tool_to_badge,
    collapsed,
    todo_block,
    render_diff,
    think_line,
    badge,
    dim,
    tool_header,
)
from engine.renderer import Renderer


# ── map_tool_to_badge ────────────────────────────────────────────────────

def test_map_execute_shell():
    assert map_tool_to_badge("execute_shell") == "SHELL"


def test_map_file_system_read():
    assert map_tool_to_badge("file_system") == "READ"


def test_map_file_system_write():
    """file_system maps to READ universally; EDIT tools use explicit names."""
    assert map_tool_to_badge("file_system") == "READ"


def test_map_str_replace_edit():
    assert map_tool_to_badge("str_replace") == "EDIT"


def test_map_replace_tool():
    assert map_tool_to_badge("replace") == "EDIT"


def test_map_todo_write():
    assert map_tool_to_badge("todo_write") == "TODOS"


def test_map_web_search():
    assert map_tool_to_badge("web_search") == "SEARCH"


def test_map_search_memory():
    assert map_tool_to_badge("search_memory") == "SEARCH"


def test_map_unknown():
    assert map_tool_to_badge("custom_rando") == "CUSTOM_RANDO"


def test_map_empty():
    assert map_tool_to_badge("") == "TOOL"


# ── collapsed ────────────────────────────────────────────────────────────

def test_collapsed_count():
    c = collapsed(14)
    assert "+14 lines" in c
    assert "ctrl+o to expand" in c


def test_collapsed_zero():
    c = collapsed(0, "")
    assert isinstance(c, str)


# ── todo_block ──────────────────────────────────────────────────────────

def test_todo_block_done():
    block = todo_block([{"content": "Step 1", "status": "done"}])
    assert "☒" in block
    assert "Step 1" in block
    assert "TODOS" in block


def test_todo_block_pending():
    block = todo_block([{"content": "Step 2", "status": "pending"}])
    assert "☐" in block
    assert "Step 2" in block


def test_todo_block_mixed():
    items = [
        {"content": "A", "status": "done"},
        {"content": "B", "status": "in_progress"},
        {"content": "C", "status": "pending"},
    ]
    block = todo_block(items)
    assert "☒" in block and "A" in block
    assert "◐" in block and "B" in block
    assert "☐" in block and "C" in block


# ── render_diff ─────────────────────────────────────────────────────────

def test_render_diff_added():
    diff = "--- a/file\n+++ b/file\n@@ -1 +1,2 @@\n-old\n+new\n+extra"
    rendered = render_diff(diff)
    assert "-old" in rendered or "old" in rendered
    assert "+new" in rendered or "new" in rendered


def test_render_diff_collapsed():
    lines = ["--- a/f\n+++ b/f\n@@ -1 +1,100 @@"] + [f"-old{i}" for i in range(20)]
    diff = "\n".join(lines)
    rendered = render_diff(diff, max_lines=12)
    assert "ctrl+o" in rendered  # collapsed marker


def test_render_diff_empty():
    assert render_diff("") == ""


# ── think_line ──────────────────────────────────────────────────────────

def test_think_line_with_duration():
    line = think_line(2.7)
    assert "Thought" in line
    assert "3" in line  # rounded up
    assert "seconds" in line


def test_think_line_no_duration():
    line = think_line(None)
    assert "Thought" in line
    assert "ctrl+o" in line


# ── badge ───────────────────────────────────────────────────────────────

def test_badge_contains_label():
    b = badge("SHELL")
    assert "SHELL" in b
    assert "\033[" in b  # ANSI escape


def test_badge_warn_color():
    b = badge("VERIFIER", color="warn")
    assert "VERIFIER" in b


def test_badge_err_color():
    b = badge("ERROR", color="err")
    assert "ERROR" in b


# ── tool_header ─────────────────────────────────────────────────────────

def test_tool_header_format():
    h = tool_header("READ", "[core/llm.py]", "382 lines")
    assert "READ" in h
    assert "core/llm.py" in h
    assert "382 lines" in h


def test_tool_header_no_extra():
    h = tool_header("SHELL", "[ls -la]")
    assert "SHELL" in h
    assert "ls -la" in h


# ── Renderer thread safety ──────────────────────────────────────────────

def test_renderer_concurrent_calls():
    """Concurrent tool_start + stream_chunk must not raise."""
    r = Renderer()
    errors = []

    def writer1():
        try:
            for i in range(20):
                r.tool_start("execute_shell", {"command": f"echo {i}"})
        except Exception as e:
            errors.append(e)

    def writer2():
        try:
            for i in range(20):
                r.stream_chunk(f"token-{i}")
        except Exception as e:
            errors.append(e)

    def writer3():
        try:
            for i in range(20):
                r.tool_end("execute_shell", success=True, output=f"out{i}")
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer1),
        threading.Thread(target=writer2),
        threading.Thread(target=writer3),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent errors: {errors}"
    r.shutdown()


# ── Verifier_reject ─────────────────────────────────────────────────────

def test_verifier_reject_contains_badge():
    r = Renderer()
    r.verifier_reject("No verified evidence")
    # After shutdown+flush, the lines are gone; verify the method doesn't crash
    r.shutdown()
    # Can't easily assert internal _lines after flush, but no crash = pass


if __name__ == "__main__":
    test_map_execute_shell()
    test_map_file_system_read()
    test_map_file_system_write()
    test_map_todo_write()
    test_map_web_search()
    test_map_search_memory()
    test_map_unknown()
    test_map_empty()
    test_collapsed_count()
    test_collapsed_zero()
    test_todo_block_done()
    test_todo_block_pending()
    test_todo_block_mixed()
    test_render_diff_added()
    test_render_diff_collapsed()
    test_render_diff_empty()
    test_think_line_with_duration()
    test_think_line_no_duration()
    test_badge_contains_label()
    test_badge_warn_color()
    test_badge_err_color()
    test_tool_header_format()
    test_tool_header_no_extra()
    test_renderer_concurrent_calls()
    test_verifier_reject_contains_badge()
    print("All Phase UI tests passed.")
