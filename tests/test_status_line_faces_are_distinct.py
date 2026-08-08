"""Am+8 C1 guard: the six visible faces must stay six.

Human ruling (Am, 2026-08-06 13:14 - "1A 2A 3B"). C1 executes 1A only.
Reasoning (assistant, accepted by that ruling): DISABLED borrows the ERROR
personality, so a disabled row renders identically to a failed one. The
contract is the rendered line, not the table behind it.
"""
from __future__ import annotations

from tests.support.render import make_console

from ui.design.primitives import StatusLine
from ui.design.state import UIState

_SIX = (
    UIState.THINKING,
    UIState.RUNNING,
    UIState.SUCCESS,
    UIState.WARNING,
    UIState.ERROR,
    UIState.DISABLED,
)


def _render(state: UIState) -> str:
    console = make_console(width=64, height=25)
    with console.capture() as cap:
        console.print(StatusLine(state, context="ctx"))
    return cap.get().rstrip("\n")


def test_disabled_does_not_wear_the_error_face():
    disabled, error = _render(UIState.DISABLED), _render(UIState.ERROR)
    assert disabled != error, (
        f"DISABLED renders exactly like ERROR: {error!r}"
    )


def test_six_states_render_six_distinct_lines():
    lines = [_render(s) for s in _SIX]
    assert len(set(lines)) == len(_SIX), lines
