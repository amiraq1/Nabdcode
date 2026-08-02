"""Typography presets.

No widget chooses typography manually. Each preset is a frozen dataclass of
(name, scale, emphasis, color). Color comes from theme.semantic; height from
tokens.Scale — so typography has exactly one owner of each concern.
"""
from __future__ import annotations

from dataclasses import dataclass

from ui.design.theme.color import Color
from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import Scale


@dataclass(frozen=True)
class TypographyPreset:
    name: str
    scale: int          # height in cells (Scale)
    bold: bool = False
    dim: bool = False
    italic: bool = False
    color: Color | None = None
    overflow: str = "ellipsis"


TERMINAL_TITLE = TypographyPreset("terminal_title", Scale.large, bold=True, color=SEMANTIC.text)
SECTION_TITLE = TypographyPreset("section_title", Scale.medium, bold=True, color=SEMANTIC.primary)
NORMAL = TypographyPreset("normal", Scale.small, color=SEMANTIC.text)
MUTED = TypographyPreset("muted", Scale.small, dim=True, color=SEMANTIC.text_muted)
CAPTION = TypographyPreset("caption", Scale.tiny, dim=True, color=SEMANTIC.caption)
CODE = TypographyPreset("code", Scale.small, color=SEMANTIC.code)
SUCCESS = TypographyPreset("success", Scale.small, bold=True, color=SEMANTIC.success)
WARNING = TypographyPreset("warning", Scale.small, bold=True, color=SEMANTIC.warning)
DANGER = TypographyPreset("danger", Scale.small, bold=True, color=SEMANTIC.danger)
THINKING = TypographyPreset("thinking", Scale.small, dim=True, color=SEMANTIC.thinking)
RUNNING = TypographyPreset("running", Scale.small, bold=True, color=SEMANTIC.running)
ERROR = TypographyPreset("error", Scale.small, bold=True, color=SEMANTIC.error)

PRESETS: dict[str, TypographyPreset] = {
    "terminal_title": TERMINAL_TITLE,
    "section_title": SECTION_TITLE,
    "normal": NORMAL,
    "muted": MUTED,
    "caption": CAPTION,
    "code": CODE,
    "success": SUCCESS,
    "warning": WARNING,
    "danger": DANGER,
    "thinking": THINKING,
    "running": RUNNING,
    "error": ERROR,
}
