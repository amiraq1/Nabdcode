"""Color value object.

This is the *only* type that materializes a concrete color literal in the
design system. Semantic tokens (theme.semantic) and no other layer hold raw
hex values, so there is exactly one place to audit when a color changes.

Third-party libraries (rich/textual) are imported lazily inside helpers so
this module stays a dependency-time leaf.
"""
from __future__ import annotations

from dataclasses import dataclass


def _validate_hex(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Color must be a str, got {type(value).__name__}")
    h = value.lstrip("#")
    if len(h) not in (3, 6, 8) or not all(c in "0123456789abcdefABCDEF" for c in h):
        raise ValueError(f"Color must be a CSS hex string ('#rgb'/'#rrggbb'/'#rrggbbaa'), got {value!r}")
    return value.lower() if len(h) == 6 else value.lower()


@dataclass(frozen=True)
class Color:
    """An immutable, normalized color. Stored as a CSS hex string."""

    hex: str

    def __post_init__(self) -> None:
        normalized = _validate_hex(self.hex)
        object.__setattr__(self, "hex", normalized)

    @property
    def rgb(self) -> tuple[int, int, int]:
        h = self.hex.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def to_rich_style(self):
        """Rich Style for the color (lazy import keeps this module a leaf)."""
        from rich.style import Style
        return Style(color=self.hex)

    def __str__(self) -> str:
        return self.hex
