"""Semantic color tokens.

Single source of truth for *meaning* of color. Widgets must never reference a
raw hex value; they read SEMANTIC.surface / SEMANTIC.primary / etc. Concrete
values are aligned to the legacy palette (see ui/theme.py) so D-0 introduces no
visual redesign — they are simply re-homed here going forward.
"""
from __future__ import annotations

from dataclasses import dataclass

from ui.design.theme.color import Color


@dataclass(frozen=True)
class SemanticTheme:
    # surface / structure
    background: Color   # app background (#000000)
    surface: Color      # raised surfaces (#0a0a0a)
    panel: Color        # bento panel background (#0d1117)
    header: Color       # header bar (#0a0a0c)
    footer: Color       # footer bar (#0a0a0c)
    border: Color       # panel borders (#1a1a1a)

    # text
    text: Color         # primary text (#f2f2f2)
    text_muted: Color   # muted text (#7a7a7a)
    text_dim: Color     # faint text (#4d4d4d)
    caption: Color      # caption / hint (#737373)
    code: Color         # code / path text (#a3a3a3)

    # palette
    primary: Color      # primary accent (#5945B1)
    primary_dim: Color  # muted primary (#4a3a94)
    secondary: Color     # secondary accent (#6943FF)
    accent: Color        # complementary accent (#6fd3d6)
    success: Color       # success (#3ecf8e)
    warning: Color       # warning (#e0b23c)
    danger: Color        # danger (#e0524a)
    error: Color         # error (#e0524a)
    info: Color          # informational (#6fd3d6)
    action_badge: Color  # action badge background (#0891B2)

    # execution / status states
    thinking: Color     # agent thinking (#6943FF)
    running: Color      # active execution (#22d3ee cyan-teal, distinct from success)
    idle: Color         # idle / inactive (#4d4d4d)
    selection: Color    # keyboard selection highlight (#00dcff)
    focus: Color         # focus ring (#00a8ff)
    disabled: Color     # disabled controls (#4d4d4d)


SEMANTIC: SemanticTheme = SemanticTheme(
    background=Color("#000000"),
    surface=Color("#0a0a0a"),
    panel=Color("#0d1117"),
    header=Color("#0a0a0c"),
    footer=Color("#0a0a0c"),
    border=Color("#1a1a1a"),
    text=Color("#f2f2f2"),
    text_muted=Color("#7a7a7a"),
    text_dim=Color("#4d4d4d"),
    caption=Color("#737373"),
    code=Color("#a3a3a3"),
    primary=Color("#5945B1"),
    primary_dim=Color("#4a3a94"),
    secondary=Color("#6943FF"),
    accent=Color("#6fd3d6"),
    success=Color("#3ecf8e"),
    warning=Color("#e0b23c"),
    danger=Color("#e0524a"),
    error=Color("#e0524a"),
    info=Color("#6fd3d6"),
    action_badge=Color("#0891B2"),
    thinking=Color("#6943FF"),
    running=Color("#22d3ee"),
    idle=Color("#4d4d4d"),
    selection=Color("#00dcff"),
    focus=Color("#00a8ff"),
    disabled=Color("#4d4d4d"),
)
