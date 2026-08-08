"""R-4.4b — Behavioral Guard: "The Answer Clock".

Under the human-judged contract (b), the status bar's clock measures the
duration of a SINGLE ANSWER: it starts at 0.0s when start() is called, grows
while the answer is running, and FREEZES at its last value when stop() is
called. A subsequent start() begins a NEW answer and resets to 0.0s.

Proven purely by execution -- never by reading the module's source text.
Time is controlled via monkeypatch on time.monotonic (no time.sleep).
The screen is read via make_console + strip_ansi only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.render import make_console, strip_ansi
from ui.widgets.status_bar import AgentStatusBar


class _Clock:
    """Controllable monotonic clock (stateful, instant, no waiting)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _screen_text(bar) -> str:
    """Snapshot the console text the bar has rendered."""
    return strip_ansi(bar._console.file.getvalue())


def test_the_clock_freezes_after_stop(monkeypatch):
    """Contract: stop() freezes the visible clock at its last value --
    advancing time after stop() must NOT move the displayed duration."""
    import time

    clock = _Clock(1000.0)
    monkeypatch.setattr(time, "monotonic", clock)

    bar = AgentStatusBar(console=make_console(width=80, height=25))
    try:
        bar.start()
        clock.advance(3.0)
        bar.set_active("Thinking")
        frozen = _screen_text(bar)
        frozen_dur = bar._get_duration()

        assert "3.0s" in frozen_dur, (
            "R-4.4b CONTRACT FAILED (freeze): expected the clock to have "
            "advanced to 3.0s before stop, got: " + repr(frozen_dur)
        )

        bar.stop()
        clock.advance(6.0)  # time keeps moving in the world...
        bar.set_active("Running Tools")  # ...but the answer is over
        after = bar._get_duration()

        assert "9.0s" not in after, (
            "R-4.4b CONTRACT FAILED (freeze): the clock kept running after "
            "stop() -- it did NOT freeze. before_stop=" + repr(frozen_dur) +
            " after_stop_with_6_more_seconds=" + repr(after)
        )
        assert "3.0s" in after, (
            "R-4.4b CONTRACT FAILED (freeze): the clock did not hold its "
            "last value of 3.0s. before_stop=" + repr(frozen_dur) +
            " after=" + repr(after)
        )
    finally:
        bar.stop()


def test_a_new_answer_starts_from_zero(monkeypatch):
    """Contract: after stop(), a new start() begins a fresh answer and
    resets the visible clock to 0.0s, then it grows again."""
    import time

    clock = _Clock(2000.0)
    monkeypatch.setattr(time, "monotonic", clock)

    bar = AgentStatusBar(console=make_console(width=80, height=25))
    try:
        bar.start()
        clock.advance(4.0)
        bar.set_active("Thinking")
        first = bar._get_duration()
        bar.stop()

        # --- a NEW answer ---
        bar.start()                       # must reset the clock
        second = bar._get_duration()      # measure BEFORE advancing time
        assert "0.0s" in second, (
            "R-4.4b CONTRACT FAILED (restart): a new answer must start from "
            "0.0s, but observed " + repr(second) +
            " (first answer was " + repr(first) + ")"
        )
        clock.advance(3.0)
        bar.set_active("Generating")
        grown = bar._get_duration()

        assert "3.0s" in grown, (
            "R-4.4b CONTRACT FAILED (restart): the new answer's clock did not "
            "grow from zero. second=" + repr(second) + " grown=" + repr(grown)
        )
        assert "4.0s" not in grown, (
            "R-4.4b CONTRACT FAILED (restart): the new answer inherited the "
            "old 4.0s instead of restarting. second=" + repr(second) +
            " grown=" + repr(grown)
        )
    finally:
        bar.stop()


def test_the_last_frame_carries_a_real_duration(monkeypatch):
    """Contract: the final frame written to the screen before stop()
    carries a real (non-zero) duration equal to the elapsed time."""
    import time

    clock = _Clock(3000.0)
    monkeypatch.setattr(time, "monotonic", clock)

    bar = AgentStatusBar(console=make_console(width=80, height=25))
    try:
        bar.start()
        clock.advance(11.0)
        bar.set_active("Generating")
        before_stop_text = _screen_text(bar)
        final_dur = bar._get_duration()

        assert "11.0s" in final_dur, (
            "R-4.4b CONTRACT FAILED (last-frame): expected 11.0s before stop, "
            "got " + repr(final_dur)
        )

        bar.stop()
        final_text = _screen_text(bar)

        assert "11.0s" in final_text, (
            "R-4.4b CONTRACT FAILED (last-frame): the last frame written to "
            "the screen did not carry a real duration. final_dur=" +
            repr(final_dur) + " last_frame=" + repr(final_text)
        )
    finally:
        bar.stop()
