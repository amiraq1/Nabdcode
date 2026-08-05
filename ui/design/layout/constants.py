"""Layout constants.

Single owner of layout geometry (panel widths, bar heights, etc.). Uses tokens
for spacing; introduces no magic numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ui.design.tokens import GAP, PADDING


@dataclass(frozen=True)
class Layout:
    header_height: int = 5
    footer_height: int = 1
    status_bar_height: int = 1
    sidebar_width: int = 36
    panel_min_width: int = 40
    panel_max_width: int = 100
    panel_default_width: int = 64
    min_content_width: int = 60
    padding: Tuple[int, int] = (PADDING.y, PADDING.x)   # (vertical, horizontal)
    widget_gap: int = GAP.widget
    wrap_width: int = 48


LAYOUT: Layout = Layout()
