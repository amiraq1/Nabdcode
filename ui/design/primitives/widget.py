"""Base Widget primitives (abstract contract shared by all widgets).

Widgets depend on primitives (not the other way around). Primitives depend on
theme only.

D-1.1: render returns a Rich ``RenderableType`` — layout and measurement are
owned by Rich, not by the widget. This is the first real test of the contract
declared PROVISIONAL in D-0; primitives are not bent to defend the old
``-> str`` signature.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from rich.console import RenderableType


class Widget(ABC):
    """Abstract base every future widget implements.

    Concrete rendering/input are supplied by widgets; this contract only fixes
    the surface area (name + render + refresh + input) so widgets stay
    interchangeable.
    """

    name: str = "widget"

    @abstractmethod
    def render(self, width: int | None = None, height: int | None = None) -> RenderableType:
        """Render the widget into a Rich renderable (Rich owns layout/measure)."""

    @abstractmethod
    def refresh(self) -> None:
        """Schedule / perform a repaint."""

    @abstractmethod
    def handle_input(self, key: str) -> bool:
        """Consume `key`. Returns True if handled, else False (fall through)."""
