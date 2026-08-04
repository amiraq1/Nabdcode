"""tests/test_status_bar_lifecycle.py — idempotent start/stop guard."""
from __future__ import annotations

from tests.support.render import make_console
from ui.widgets.status_bar import AgentStatusBar


def test_status_bar_idempotent_start_stop() -> None:
    """start()/stop() are idempotent and release the Live lock."""
    bar = AgentStatusBar(make_console())
    bar.start()
    bar.start()
    bar.stop()
    bar.stop()
    assert bar._running is False
    assert bar._live is None
