"""Am+8 C2 guard: the display verbs are Am's own words.

Human ruling (Am, 2026-08-06 17:18 - "V1 R1").
Reasoning (assistant, accepted by that ruling): a guard that merely forbids
Latin text passes for any junk string; the contract is the exact ruled word.
"""

from __future__ import annotations

from ui.design.primitives.personality import (
    Personality,
    _PERSONALITY_STYLE,
    style_of,
)
from ui.design.state import UIState

_RULED = {
    Personality.THINKING: "يفكّر",
    Personality.RUNNING: "يُنفّذ",
    Personality.SUCCESS: "تمّ",
    Personality.WARNING: "تحذير",
    Personality.ERROR: "فشل",
    Personality.DISABLED: "معطّل",
}


def test_every_personality_carries_its_ruled_verb():
    assert set(_PERSONALITY_STYLE) == set(_RULED), (
        "the personality set moved"
    )

    actual = {
        personality: style.verb
        for personality, style in _PERSONALITY_STYLE.items()
    }

    assert actual == _RULED


def test_display_verb_is_not_the_enum_identifier():
    for state in UIState:
        style = style_of(state)
        assert style.verb != style.personality.value, state.name
