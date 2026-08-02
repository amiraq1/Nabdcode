"""Animation profile definitions (definitions only — NOT implemented).

D-0 defines the vocabulary future widgets will consume. No animation is
executed at this layer; profiles reference durations in tokens.AnimationSpeed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ui.design.tokens import AnimationSpeed


class AnimationProfile(Enum):
    """Named animation profiles (future widgets consume these)."""

    NONE = "none"
    SUBTLE = "subtle"
    THINKING = "thinking"
    STREAMING = "streaming"
    PULSE = "pulse"
    BLINK = "blink"
    PROGRESS = "progress"
    TRANSITION = "transition"


class Spinner(Enum):
    """Spinner render styles (future widgets consume these)."""

    NONE = "none"
    DOTS = "dots"
    LINE = "line"
    ELAPSE = "elapse"
    PULSE = "pulse"
    WAVE = "wave"
    BRAILLE = "braille"


@dataclass(frozen=True)
class AnimationSpec:
    """Static description of an animation (no runtime animation in D-0)."""

    profile: AnimationProfile
    spinner: Spinner = Spinner.NONE
    speed: float = AnimationSpeed.normal
    loop: bool = False
    note: str = "definition only — animation implementation is deferred"
