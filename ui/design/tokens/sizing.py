"""Sizing / metric tokens — single owner of geometry metrics.

Border radius, elevation levels, density, durations, and the size scale.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Radius:
    """Border radius in cells (textual/Rich box radius)."""

    none: int = 0
    sm: int = 1
    md: int = 2
    lg: int = 4
    full: int = 999


RADIUS: Radius = Radius()


@dataclass(frozen=True)
class Elevation:
    """Elevation levels (z/depth abstraction; consumers map to shadow/blur)."""

    level0: int = 0
    level1: int = 1
    level2: int = 2
    level3: int = 3


ELEVATION: Elevation = Elevation()


@dataclass(frozen=True)
class Density:
    """Panel density presets."""

    compact: int = 0
    normal: int = 1
    spacious: int = 2


DENSITY: Density = Density()


@dataclass(frozen=True)
class ProgressDensity:
    """Progress-bar resolution (cells)."""

    low: int = 8
    medium: int = 16
    high: int = 32


PROGRESS_DENSITY: ProgressDensity = ProgressDensity()


@dataclass(frozen=True)
class AnimationSpeed:
    """Durations in seconds (definitions; animation impl comes later)."""

    instant: float = 0.0
    fast: float = 0.1
    normal: float = 0.25
    slow: float = 0.5


ANIMATION_SPEED: AnimationSpeed = AnimationSpeed()


@dataclass(frozen=True)
class Scale:
    """Content height scale in cells (used by typography)."""

    tiny: int = 16
    small: int = 20
    medium: int = 28
    large: int = 36
    xlarge: int = 48


SCALE: Scale = Scale()
