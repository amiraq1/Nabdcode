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
    header_after_logo: int = 1  # blank line between logo and status row
    footer_indent: int = 2      # leading indent of the footer hint bar


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


@dataclass(frozen=True)
class Gutter:
    """Fixed-width list gutter (D-3c.3): two independent slots, in cells.

    Single owner of the gutter width. Slot widths equal the wcwidth of the
    glyph each slot holds (❯ selection / ► collapse), so an inactive slot
    is a same-width space and the status column never shifts.
    """

    selection_slot: int = 1  # wcwidth of ❯ (U+276F)
    collapse_slot: int = 1   # wcwidth of ► (U+25BA)

    @property
    def width(self) -> int:
        return self.selection_slot + self.collapse_slot


GUTTER: Gutter = Gutter()
