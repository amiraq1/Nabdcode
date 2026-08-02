"""ui.design — D-0 UI infrastructure for the Am+8 TUI Design System.

Additive foundation only. Does NOT modify any existing widget, theme, or
behavior. Future D-1..D-8 work consumes these modules to migrate the legacy
ui/theme.py / engine/ui_theme.py duplication into this single source of truth.

Dependency hierarchy (strict, acyclic):

    widgets (future)
        -> primitives
            -> theme
                -> tokens

    icons, animation  (leaf peers)
    typography -> theme + tokens
    layout      -> tokens
    state       -> theme + icons + animation
    contracts   -> primitives + theme + state + icons
"""
from ui.design.theme import Color, SEMANTIC, SemanticTheme
from ui.design.tokens import (
    SPACING, GAP, PADDING, MARGIN, RADIUS, ELEVATION, DENSITY,
    PROGRESS_DENSITY, ANIMATION_SPEED, SCALE,
)
from ui.design.icons import Icon
from ui.design.animation import AnimationProfile, Spinner, AnimationSpec
from ui.design.typography import TypographyPreset, PRESETS
from ui.design.layout import Layout, LAYOUT
from ui.design.state import UIState, StateRecord, UI_STATES, state_of
from ui.design.primitives import Widget
from ui.design.contracts import (
    StatusWidget, ToolWidget, PanelWidget, CardWidget, ListWidget,
    DialogWidget, FooterWidget, HeaderWidget, ProgressWidget, SpinnerWidget,
)

__all__ = [
    "Color", "SEMANTIC", "SemanticTheme",
    "SPACING", "GAP", "PADDING", "MARGIN", "RADIUS", "ELEVATION", "DENSITY",
    "PROGRESS_DENSITY", "ANIMATION_SPEED", "SCALE",
    "Icon", "AnimationProfile", "Spinner", "AnimationSpec",
    "TypographyPreset", "PRESETS", "Layout", "LAYOUT",
    "UIState", "StateRecord", "UI_STATES", "state_of",
    "Widget",
    "StatusWidget", "ToolWidget", "PanelWidget", "CardWidget", "ListWidget",
    "DialogWidget", "FooterWidget", "HeaderWidget", "ProgressWidget", "SpinnerWidget",
]
