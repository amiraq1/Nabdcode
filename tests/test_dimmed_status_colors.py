"""tests/test_dimmed_status_colors.py — UX-11: dim status bar colors."""

from ui.cc_style import status_compact_line

def test_status_line_exists() -> None:
    """ع1 status_line_exists: status_compact_line قابلة للاستدعاء."""
    text = status_compact_line(1, 0.0)
    assert text is not None

def test_colors_dimmed() -> None:
    """ع2 colors_dimmed: تحتوي على "dim" أو ألوان داكنة."""
    # We'll check the source code of status_compact_line for "dim green", "dim cyan", etc.
    from pathlib import Path
    source = Path("ui/cc_style.py").read_text()
    
    # Check that "green" is not used without "dim"
    # Actually, a simple check: style="dim green" or style="dim cyan" should exist.
    assert 'style="dim green"' in source or 'style="dark_green"' in source
    assert 'style="dim cyan"' in source or 'style="grey62"' in source

def test_no_bright_colors() -> None:
    """ع3 no_bright_colors: لا تحتوي على ألوان زاهية كـ style="green"."""
    from pathlib import Path
    source = Path("ui/cc_style.py").read_text()
    
    # We should ensure that style="green" and style="cyan" are not used in status_compact_line
    # We can extract the function body to be safer.
    import re
    func_match = re.search(r"def status_compact_line\(.*?\)\s*->.*?\"\"\"(.*?)(?=def \w|\Z)", source, re.DOTALL)
    if func_match:
        body = func_match.group(0)
        assert 'style="green"' not in body
        assert 'style="cyan"' not in body
