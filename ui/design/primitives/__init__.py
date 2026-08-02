"""Primitives layer: abstract Widget contract + D-1 concrete atoms."""
from ui.design.primitives.widget import Widget
from ui.design.primitives.personality import (
    Personality, PersonalityStyle, style_of, personality_of, spinner_frame_for,
)
from ui.design.primitives.status_line import StatusLine
from ui.design.primitives.spinner import Spinner
from ui.design.primitives.section_panel import SectionPanel
from ui.design.primitives.key_value_row import KeyValueRow
from ui.design.primitives.divider import Divider
from ui.design.primitives.badge import Badge
from ui.design.primitives.layout import Row, Column

__all__ = [
    "Widget",
    "Personality", "PersonalityStyle", "style_of", "personality_of", "spinner_frame_for",
    "StatusLine", "Spinner", "SectionPanel", "KeyValueRow", "Divider", "Badge",
    "Row", "Column",
]
