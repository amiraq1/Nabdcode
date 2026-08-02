"""D-1 personality resolver.

Maps all 14 UIStates onto 5 StatusLine personalities so StatusLine stays ONE
component while every state is rendered with explicit, tested styling (no state
falls through unstyled).

D-1.1: each personality owns a DISTINCT (color, icon) pair plus distinct weight
and rhythm so RUNNING and SUCCESS can never visually collapse into one.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ui.design.theme.color import Color
from ui.design.theme.semantic import SEMANTIC
from ui.design.icons import Icon
from ui.design.animation import Spinner as SpinnerEnum
from ui.design.state import UIState, UI_STATES


class Personality(Enum):
    """The five StatusLine personalities (one component, five faces)."""

    THINKING = "thinking"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class PersonalityStyle:
    """Per-personality rendering data.

    Distinctness lives in WEIGHT and RHYTHM too, not color alone:
      - weight:  dim / bold / normal  (typographic emphasis)
      - rhythm:  static vs stream|pulse (motion affordance; impl is D-1 part 2)
    A (color, icon) distinctness is enforced by the permanent guard test.
    """

    personality: Personality
    verb: str
    color: Color
    icon: Icon
    weight: str
    rhythm: str
    spinner: SpinnerEnum
    animated: bool


# explicit TOTAL mapping of all 14 UIStates -> 5 personalities
_PERSONALITY_OF: dict[UIState, Personality] = {
    UIState.IDLE:         Personality.THINKING,
    UIState.THINKING:     Personality.THINKING,
    UIState.PLANNING:     Personality.THINKING,
    UIState.RUNNING:      Personality.RUNNING,
    UIState.STREAMING:    Personality.RUNNING,
    UIState.BUSY:         Personality.RUNNING,
    UIState.SUCCESS:      Personality.SUCCESS,
    UIState.COMPLETED:    Personality.SUCCESS,
    UIState.WARNING:      Personality.WARNING,
    UIState.WAITING:      Personality.WARNING,
    UIState.LOADING:      Personality.WARNING,
    UIState.ERROR:        Personality.ERROR,
    UIState.CANCELLED:    Personality.ERROR,
    UIState.DISABLED:     Personality.ERROR,   # fixed: was a NameError in draft
}

_PERSONALITY_STYLE: dict[Personality, PersonalityStyle] = {
    Personality.THINKING: PersonalityStyle(
        Personality.THINKING, "thinking", SEMANTIC.thinking, Icon.THINKING,
        "dim", "stream", SpinnerEnum.DOTS, True,
    ),
    Personality.RUNNING: PersonalityStyle(
        Personality.RUNNING, "running", SEMANTIC.running, Icon.RUNNING,
        "bold", "stream", SpinnerEnum.LINE, True,
    ),
    Personality.SUCCESS: PersonalityStyle(
        Personality.SUCCESS, "ok", SEMANTIC.success, Icon.SUCCESS,
        "bold", "static", SpinnerEnum.NONE, False,
    ),
    Personality.WARNING: PersonalityStyle(
        Personality.WARNING, "warn", SEMANTIC.warning, Icon.WARNING,
        "bold", "pulse", SpinnerEnum.PULSE, True,
    ),
    Personality.ERROR: PersonalityStyle(
        Personality.ERROR, "error", SEMANTIC.error, Icon.ERROR,
        "bold", "static", SpinnerEnum.NONE, False,
    ),
}

# static proxy glyph per D-0 Spinner style (reuses EXISTING registry icons only)
_SPINNER_FRAME: dict[SpinnerEnum, str] = {
    SpinnerEnum.DOTS:    Icon.glyph(Icon.LOADING),
    SpinnerEnum.LINE:    Icon.glyph(Icon.RUNNING),
    SpinnerEnum.BRAILLE: Icon.glyph(Icon.STREAMING),
    SpinnerEnum.ELAPSE:  Icon.glyph(Icon.WAITING),
    SpinnerEnum.PULSE:   Icon.glyph(Icon.THINKING),
    SpinnerEnum.WAVE:    Icon.glyph(Icon.THINKING),
    SpinnerEnum.NONE:    "",
}


def personality_of(state: UIState) -> Personality:
    """Resolve any of the 14 UIStates to one of the 5 personalities."""
    return _PERSONALITY_OF[state]


def style_of(state: UIState) -> PersonalityStyle:
    """Resolve the full PersonalityStyle for a state."""
    return _PERSONALITY_STYLE[personality_of(state)]


def spinner_frame_for(state: UIState) -> str:
    """Static frame glyph for a state (empty for non-animated personalities)."""
    rec = UI_STATES[state]
    style = _PERSONALITY_STYLE[personality_of(state)]
    if not style.animated:
        return ""
    return _SPINNER_FRAME.get(rec.spinner, "")


def to_style_str(weight: str) -> str:
    """Map a semantic weight to a Rich style-string token ("" | "bold" | "dim")."""
    if weight == "bold":
        return "bold"
    if weight == "dim":
        return "dim"
    return ""
