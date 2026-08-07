"""C2 Guard: Ensure AgentStatusBar uses time.monotonic for duration."""

from __future__ import annotations

import pathlib

def test_status_bar_uses_monotonic():
    """C2: AgentStatusBar must use time.monotonic for duration."""
    source = pathlib.Path('ui/widgets/status_bar.py').read_text(encoding='utf-8')
    
    # 1. Check import
    assert 'import time' in source or 'from time import' in source, "time module not imported"
    
    # 2. Check usage of monotonic
    assert 'monotonic' in source, "time.monotonic not used"
