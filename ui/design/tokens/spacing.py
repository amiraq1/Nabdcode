"""Spacing tokens — single owner of all layout distances.

Numeric cell-based scales only. No colors, no typography. Distance values are
read by theme (semantic uses none here) and layout/typography; layout is the
only other consumer, so there is zero duplication.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Spacing:
    """Cell-based spacing scale (0 = none)."""

    xxs: int = 0
    xs: int = 1
    sm: int = 2
    md: int = 3
    lg: int = 4
    xl: int = 6
    xxl: int = 8


SPACING: Spacing = Spacing()


@dataclass(frozen=True)
class Gap:
    """Gaps between UI elements (cells)."""

    icon: int = 1
    status: int = 2
    widget: int = 2
    section: int = 3
    panel: int = 4


GAP: Gap = Gap()


@dataclass(frozen=True)
class Padding:
    """Default padding (vertical, horizontal) in cells."""

    y: int = 0
    x: int = 1


PADDING: Padding = Padding()


@dataclass(frozen=True)
class Margin:
    """Default margins (cells)."""

    section: int = 1


MARGIN: Margin = Margin()
