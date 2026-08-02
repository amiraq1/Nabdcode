"""Theme layer: Color primitive + semantic color tokens.

Ownership (dependency direction):
    tokens <- theme <- primitives <- widgets
Color literals live ONLY in this package (color._validate_hex / SemanticTheme).
"""
from ui.design.theme.color import Color
from ui.design.theme.semantic import SemanticTheme, SEMANTIC

__all__ = ["Color", "SemanticTheme", "SEMANTIC"]
