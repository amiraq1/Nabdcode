# core/taste_engine.py
"""core/taste_engine.py — Neuro-Symbolic Taste Engine (taste-1 architecture port).

Stores, loads, and synthesizes the developer's architectural preferences, coding style,
and UI rules into a persistent JSON profile (.nabd/taste_profile.json) with in-memory caching.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

try:
    from pydantic import BaseModel, Field
except Exception:
    from tools.base import BaseModel, Field


class TasteProfile(BaseModel):
    """Schema defining the developer's coding, architectural, and language preferences."""
    architectural_rules: List[str] = Field(
        default=[
            "Prefer zero-dependency solutions when possible.",
            "Use modular and decoupled design.",
        ],
        description="Core architecture and design patterns.",
    )
    code_styling: List[str] = Field(
        default=[
            "Use standard Python typing.",
            "Use Pydantic for data validation.",
        ],
        description="Syntax, typing, and formatting preferences.",
    )
    language_preferences: List[str] = Field(
        default=[
            "Interact with the user in Arabic.",
            "Write code, comments, and logs in English.",
        ],
        description="Language and UI interaction rules.",
    )
    custom_rules: List[str] = Field(
        default=[],
        description="Any other specific developer preferences learned over time.",
    )


class TasteEngine:
    """Core engine managing TasteProfile loading, persistence, in-memory caching, and prompt synthesis."""

    def __init__(self, workspace_dir: str | Path) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.profile_path = os.path.join(str(self.workspace_dir), ".nabd", "taste_profile.json")
        self._cached_profile: Optional[TasteProfile] = None

        # Ensure sandbox / config directory exists
        os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)

    def load_profile(self) -> TasteProfile:
        """Load profile from in-memory cache if available, otherwise from disk or defaults."""
        if self._cached_profile is not None:
            return self._cached_profile

        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._cached_profile = TasteProfile(**data)
            except Exception as exc:
                print(f"[Taste Engine] Error loading profile, falling back to defaults: {exc}")
                self._cached_profile = TasteProfile()
        else:
            self._cached_profile = TasteProfile()
            self.save_profile(self._cached_profile)

        return self._cached_profile

    def save_profile(self, profile: TasteProfile) -> None:
        """Persist taste profile to disk and update in-memory cache."""
        self._cached_profile = profile
        dump_data = profile.model_dump() if hasattr(profile, "model_dump") else profile.dict()
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, indent=4, ensure_ascii=False)

    def get_taste_summary_for_prompt(self) -> str:
        """Generate formatted markdown summary of taste rules for system prompt injection."""
        profile = self.load_profile()
        summary = "## Developer Taste Profile (Mandatory Rules)\n\n"

        summary += "### Architectural Rules:\n"
        for rule in profile.architectural_rules:
            summary += f"- {rule}\n"

        summary += "\n### Code Styling:\n"
        for rule in profile.code_styling:
            summary += f"- {rule}\n"

        summary += "\n### Language & Interaction:\n"
        for rule in profile.language_preferences:
            summary += f"- {rule}\n"

        if profile.custom_rules:
            summary += "\n### Custom Developer Rules:\n"
            for rule in profile.custom_rules:
                summary += f"- {rule}\n"

        return summary.strip() + "\n"
