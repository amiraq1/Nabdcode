"""R-4.3 — Behavioral Red Guard: "The Frame That Redraws Itself".

Proves, by execution (never by source inspection), that the AgentStatusBar
redraws its frame on explicit state change with NO background thread:

  Contract 1 — the clock shows: after start(), advancing the monotonic
                clock by a known amount, and a state change through the
                public API, the captured console text contains the NEW
                duration, not [0.0s].
  Contract 2 — the frame changes: two console snapshots (before and after
                a phase change) must differ, and the second must carry the
                newly active phase.
  Contract 3 — no background thread: after start(), the live-thread count
                (threading.enumerate()) must not grow — the battery fence.

Time is CONTROLLED via monkeypatch on time.monotonic (the time source the
module uses), never awaited with time.sleep.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.render import make_console, strip_ansi
from ui.widgets.status_bar import AgentStatusBar


class _Clock:
    """Controllable monotonic clock."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_bar(monkeypatch, clock) -> AgentStatusBar:
    bar = AgentStatusBar(console=make_console(width=80, height=25))
    return bar


def _snapshot(bar: AgentStatusBar) -> str:
    """Capture the console buffer content, ANSI-stripped."""
    raw = bar._console.file.getvalue()
    return strip_ansi(raw)


def test_the_clock_shows_the_new_duration(monkeypatch):
    """Contract 1: after a state change, the console shows the NEW duration."""
    import time

    clock = _Clock(start=1000.0)
    monkeypatch.setattr(time, "monotonic", clock)

    bar = _make_bar(monkeypatch, clock)
    try:
        bar.start()
        clock.advance(12.5)
        bar.set_active("Thinking")

        text = _snapshot(bar)

        assert "12.5" in text, (
            "R-4.3 CONTRACT FAILED (clock): expected the NEW duration "
            "'[12.5s]' to appear in the console after start() + advance(12.5) "
            "+ set_active('Thinking'), but the console text does not contain "
            "the new duration. Frame: " + repr(text)
        )
    finally:
        bar.stop()


def test_the_frame_changes_on_phase_change(monkeypatch):
    """Contract 2: two snapshots before/after a phase change must differ."""
    import time

    clock = _Clock(start=2000.0)
    monkeypatch.setattr(time, "monotonic", clock)

    bar = _make_bar(monkeypatch, clock)
    try:
        bar.start()
        bar.set_active("Thinking")
        before = _snapshot(bar)

        bar.set_active("Running Tools")
        after = _snapshot(bar)

        assert before != after, (
            "R-4.3 CONTRACT FAILED (frame): the console text did not change "
            "when the phase changed from 'Thinking' to 'Running Tools'. "
            "Before: " + repr(before) + " After: " + repr(after)
        )
        assert "Running Tools" in after, (
            "R-4.3 CONTRACT FAILED (frame): the second snapshot does not carry "
            "the newly active phase 'Running Tools'. After: " + repr(after)
        )
    finally:
        bar.stop()


def test_no_background_thread_is_spawned(monkeypatch):
    """Contract 3: start() must not spawn any new live thread — battery fence."""
    import time

    clock = _Clock(start=3000.0)
    monkeypatch.setattr(time, "monotonic", clock)

    bar = _make_bar(monkeypatch, clock)
    before = set(threading.enumerate())
    try:
        bar.start()
        after = set(threading.enumerate())

        assert after == before, (
            "R-4.3 CONTRACT FAILED (battery): start() spawned a new thread. "
            "Before: " + repr(before) + " After: " + repr(after)
        )
    finally:
        bar.stop()
