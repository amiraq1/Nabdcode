"""Prompt widgets for user interaction."""

from __future__ import annotations

from typing import Any
from textual.widgets import Static


class ActivePromptInput(Static):
    """Widget displaying an active prompt or inquiry to the user."""

    def __init__(self, prompt_text: str = "", **kwargs: Any) -> None:
        self.prompt_text = prompt_text
        super().__init__(f"❓ {prompt_text}", classes="active-prompt-input", **kwargs)


class Prompt(Static):
    """Stateless presentation widget displaying user prompt text."""

    def __init__(self, text: str = "", **kwargs: Any) -> None:
        self.prompt_text = text
        super().__init__(f"[USER] {text}", classes="user-msg-block prompt-widget", **kwargs)
