"""Base Widget primitives (abstract contract shared by all widgets).

Widgets depend on primitives (not the other way around). Primitives depend on
theme only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Widget(ABC):
    """Abstract base every future widget implements.

    Concrete rendering/input are supplied by widgets; this contract only fixes
    the surface area (name + render + refresh + input) so widgets stay
    interchangeable.
    """

    name: str = "widget"

    @abstractmethod
    def render(self, width: int, height: int) -> str:
        """Render the widget into a string of at most (width x height) cells."""

    @abstractmethod
    def refresh(self) -> None:
        """Schedule / perform a repaint."""

    @abstractmethod
    def handle_input(self, key: str) -> bool:
        """Consume `key`. Returns True if handled, else False (fall through)."""
