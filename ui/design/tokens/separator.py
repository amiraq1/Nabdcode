"""Separator tokens — single owner of every boundary glyph.

One definition (Separator), one owner (SEPARATOR). Glyphs and their colors
resolve through SEMANTIC like every color before them; no widget types a
separator literal — atoms apply the token (guard: test_no_literal_separators_in_widgets).
"""
from __future__ import annotations

from dataclasses import dataclass

from ui.design.theme.color import Color
from ui.design.theme.semantic import SEMANTIC


@dataclass(frozen=True)
class Separator:
    """A boundary glyph plus its SEMANTIC-derived color."""

    glyph: str
    color: Color


@dataclass(frozen=True)
class Separators:
    """The named separator instances — glyphs exist nowhere else."""

    key_value: Separator
    group: Separator


SEPARATOR: Separators = Separators(
    key_value=Separator(":", SEMANTIC.text_dim),
    group=Separator("│", SEMANTIC.text_dim),
)
