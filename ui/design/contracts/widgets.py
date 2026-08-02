"""Abstract widget interface contracts (future implementations, not now).

D-0 defines the interfaces only. No widget is migrated here (Non Goals).
Dependency direction: widgets -> primitives -> theme -> tokens.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ui.design.icons import Icon
from ui.design.primitives import Widget
from ui.design.state import UIState


class StatusWidget(Widget):
    @abstractmethod
    def set_state(self, state: UIState) -> None: ...
    @abstractmethod
    def set_label(self, label: str) -> None: ...


class ToolWidget(Widget):
    @abstractmethod
    def set_tool(self, tool_name: str) -> None: ...
    @abstractmethod
    def set_arguments(self, args: dict) -> None: ...


class PanelWidget(Widget):
    @abstractmethod
    def set_title(self, title: str) -> None: ...
    @abstractmethod
    def set_border(self, enabled: bool) -> None: ...


class CardWidget(Widget):
    @abstractmethod
    def set_elevation(self, level: int) -> None: ...


class ListWidget(Widget):
    @abstractmethod
    def set_items(self, items: list) -> None: ...
    @abstractmethod
    def select(self, index: int) -> None: ...


class DialogWidget(Widget):
    @abstractmethod
    def set_message(self, message: str) -> None: ...
    @abstractmethod
    def set_confirm_label(self, label: str) -> None: ...


class FooterWidget(Widget):
    @abstractmethod
    def set_hint(self, hint: str) -> None: ...


class HeaderWidget(Widget):
    @abstractmethod
    def set_title(self, title: str) -> None: ...


class ProgressWidget(Widget):
    @abstractmethod
    def set_progress(self, fraction: float) -> None: ...


class SpinnerWidget(Widget):
    @abstractmethod
    def set_spinner(self, spinner: str) -> None: ...
