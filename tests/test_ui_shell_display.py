import pytest
from ui.widgets.tool_result import ToolResultWidget
from rich.syntax import Syntax

def test_traceback_coloring():
    """V-03: Traceback output should be colored using Syntax (pytb)."""
    tb_output = "Traceback (most recent call last):\n  File \"main.py\", line 10, in <module>\nValueError: oops"
    widget = ToolResultWidget(tool_name="python", output=tb_output)
    panel = widget._render_expanded()
    # The renderable inside the panel should be a Syntax object
    assert isinstance(panel.renderable, Syntax)
    assert panel.renderable.lexer.name == "Python Traceback"

def test_path_truncation():
    """V-05: Long paths in args should be truncated smartly."""
    # Short path, no truncation
    widget_short = ToolResultWidget(
        tool_name="read_file",
        args={"path": "/short/path.py"}
    )
    header = widget_short._build_header_markup()
    assert "/short/path.py" in header
    assert "..." not in header

    # Long path, should be truncated in the middle
    long_path = "/home/user/workspace/smart-agent/core/some_very_long_module_name_that_exceeds_forty_chars.py"
    widget_long = ToolResultWidget(
        tool_name="read_file",
        args={"path": long_path}
    )
    header = widget_long._build_header_markup()
    # It should not contain the full path
    assert long_path not in header
    # It should contain the middle truncation marker
    assert "..." in header
    # The rendered args preview should be exactly 39 chars if it was truncated, but actually it's length 39 because of the slicing
    preview = widget_long._format_args_preview()
    assert len(preview) == 39
    assert preview.startswith("/home/user/worksp")
    assert preview.endswith("orty_chars.py")

    # Command argument test
    long_cmd = "grep -rn \"bus.emit\\|\\.emit(\" engine/ core/ 2>/dev/null | grep -v __pycache__ | head -30"
    widget_cmd = ToolResultWidget(
        tool_name="shell",
        args={"command": long_cmd}
    )
    cmd_preview = widget_cmd._format_args_preview()
    assert len(cmd_preview) == 39
    assert "..." in cmd_preview

def test_v07_smart_collapse():
    """V-07: Ensure massive single-line outputs (like minified JSON) are collapsed."""
    from ui.widgets.tool_result import ToolResultWidget
    # Short single line should NOT collapse
    short_json = '{"status": "ok"}'
    widget_short = ToolResultWidget(tool_name="repo_scanner", output=short_json)
    widget_short.render() # triggers _count_visible_lines
    assert widget_short.line_count == 1
    
    # Long single line should collapse (will wrap over many visual lines)
    long_json = '{"results": [' + ', '.join(['{"path": "/some/very/long/path/to/a/file/that/takes/up/space/and/causes/wrap/issue.py"}'] * 20) + ']}'
    widget_long = ToolResultWidget(tool_name="repo_scanner", output=long_json)
    widget_long.render() # triggers _count_visible_lines
    # Should be bumped over the threshold
    assert widget_long.line_count > widget_long.COLLAPSE_THRESHOLD
