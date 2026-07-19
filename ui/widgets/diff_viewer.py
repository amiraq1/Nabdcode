"""Diff viewing widget for displaying code edits and proposals."""

from __future__ import annotations

from typing import Any
from textual.widgets import Static


class DiffBlock(Static):
    """Widget displaying file modifications in a syntax/diff formatted box."""

    def __init__(
        self,
        diff_data: str = "",
        file: str = "",
        additions: int = 0,
        removals: int = 0,
        **kwargs: Any,
    ) -> None:
        self.diff_data = diff_data
        self.file = file
        self.additions = additions
        self.removals = removals
        super().__init__(self._format_content(), classes="diff-block", **kwargs)

    def _format_content(self) -> str:
        if self.additions or self.removals:
            header = f"📝 MODIFIED [{self.file}] (+{self.additions} / -{self.removals})"
        else:
            header = f"📝 MODIFIED [{self.file}]"
        return f"{header}\n\n{self.diff_data}"
