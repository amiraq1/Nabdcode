"""Spinner widget for busy state visual feedback."""

from __future__ import annotations

from typing import Any
from textual.widgets import Static


class Spinner(Static):
    """Stateless presentation widget displaying a loading spinner/indicator."""

    def __init__(self, text: str = "Processing...", icon: str = "⏳", **kwargs: Any) -> None:
        self.spinner_text = text
        self.spinner_icon = icon
        super().__init__(f"{icon} {text}", classes="spinner-widget", **kwargs)

    def update_text(self, text: str) -> None:
        """Update the displayed spinner label text."""
        self.spinner_text = text
        self.update(f"{self.spinner_icon} {text}")
