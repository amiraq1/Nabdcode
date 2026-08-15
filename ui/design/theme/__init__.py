"""Theme layer: Color primitive + semantic color tokens.

Ownership (dependency direction):
    tokens <- theme <- primitives <- widgets
Color literals live ONLY in this package (color._validate_hex / SemanticTheme).
"""
from ui.design.theme.color import Color
from ui.design.theme.semantic import SemanticTheme, SEMANTIC

__all__ = ["Color", "SemanticTheme", "SEMANTIC", "colors_enabled"]


def colors_enabled(*, force_terminal: bool = False) -> bool:
    """Return True when ANSI color output is allowed.

    Color is disabled when any of these hold:
      * ``NO_COLOR`` is set (any non-empty value, per the NO_COLOR spec)
      * ``TERM`` is ``dumb`` (a plain, non-ANSI terminal)

    ``force_terminal`` is accepted for API compatibility; the gate itself
    does NOT depend on whether stdout is a TTY (Rich callers decide that
    separately), so captured output and tests behave predictably.
    """
    import os

    if os.environ.get("NO_COLOR", ""):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return True
