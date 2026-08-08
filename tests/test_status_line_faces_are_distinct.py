"""Am+8 C1 guard: the seven visible faces must stay seven.

Human ruling (Am, 2026-08-06 13:14 - "1A 2A 3B"). C1 executes 1A only.
Reasoning (assistant, accepted by that ruling): DISABLED borrows the ERROR
personality, so a disabled row renders identically to a failed one. The
contract is the rendered line, not the table behind it.
"""
from __future__ import annotations

from tests.support.render import make_console

from ui.design.primitives import StatusLine
from ui.design.state import UIState

_FACES = (
    UIState.THINKING,
    UIState.RUNNING,
    UIState.SUCCESS,
    UIState.WARNING,
    UIState.ERROR,
    UIState.DISABLED,
    UIState.IDLE,
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


def test_seven_states_render_seven_distinct_lines():
    lines = [_render(s) for s in _FACES]
    assert len(set(lines)) == len(_FACES), dict(zip((st.name for st in _FACES), lines))


# Widened by human ruling (Am, 2026-08-08 - R-4.5.1): the seventh face
# Personality.PENDING (UIState.IDLE) now carries distinctness coverage.
