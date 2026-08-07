"""C4 Guard: Ensure think_line and thought_start/end are fully removed."""

import ast
import pathlib

def test_think_line_is_removed_from_ui_theme():
    """C4: think_line function must be removed from ui_theme.py."""
    source = pathlib.Path('engine/ui_theme.py').read_text()
    assert 'def think_line' not in source, "think_line function still exists in ui_theme.py"

def test_thought_methods_removed_from_renderer():
    """C4: thought_start and thought_end must be removed from renderer.py."""
    source = pathlib.Path('engine/renderer.py').read_text()
    assert 'def thought_start' not in source, "thought_start still exists in renderer.py"
    assert 'def thought_end' not in source, "thought_end still exists in renderer.py"
    assert 'think_line' not in source, "think_line import still exists in renderer.py"

def test_main_does_not_call_thought_methods():
    """C4: main.py must not call renderer.thought_start or thought_end."""
    source = pathlib.Path('main.py').read_text()
    assert 'renderer.thought_start()' not in source, "main.py still calls renderer.thought_start()"
    assert 'renderer.thought_end()' not in source, "main.py still calls renderer.thought_end()"
