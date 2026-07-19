# tools/taste_manager.py
"""tools/taste_manager.py — Taste Manager Tool for neuro-symbolic taste adaptation.

Allows the agent to view or modify the developer's TasteProfile in response to explicit
corrections or instructions from the user.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Optional

try:
    from pydantic import BaseModel, Field
except Exception:
    from tools.base import BaseModel, Field

from core.taste_engine import TasteEngine
from tools.base import BaseTool
from tools.models import ToolResult


class TasteManagerArgs(BaseModel):
    """Arguments for TasteManagerTool."""
    action: str = Field(
        ...,
        description="The action to perform: 'view' (to see current taste), 'add_rule', or 'remove_rule'.",
    )
    category: Optional[str] = Field(
        None,
        description="The category to modify: 'architectural_rules', 'code_styling', 'language_preferences', or 'custom_rules'.",
    )
    rule: Optional[str] = Field(
        None,
        description="The exact text of the rule to add or remove.",
    )


class TasteManagerTool(BaseTool):
    """Manage and update the developer's Neuro-Symbolic Taste Profile (.nabd/taste_profile.json)."""

    name: Final[str] = "taste_manager"
    description: Final[str] = (
        "Manage and update the developer's Neuro-Symbolic Taste Profile. "
        "Use this tool when the user explicitly corrects your coding style, architecture, "
        "or asks you to 'remember' a specific preference for all future interactions."
    )
    args_schema = TasteManagerArgs

    def __init__(self, taste_engine: Optional[TasteEngine] = None, workspace: str | Path = ".") -> None:
        super().__init__()
        self.taste_engine = taste_engine or TasteEngine(workspace_dir=workspace)

    def forward(self, action: str, category: Optional[str] = None, rule: Optional[str] = None) -> str:
        """Smolagents and direct execution entry point."""
        profile = self.taste_engine.load_profile()

        # 1. View current taste
        if action == "view":
            return self.taste_engine.get_taste_summary_for_prompt()

        if action not in ("add_rule", "remove_rule"):
            return "Error: Invalid action. Use 'view', 'add_rule', or 'remove_rule'."

        # Validate category before mutation
        valid_categories = ["architectural_rules", "code_styling", "language_preferences", "custom_rules"]
        if category not in valid_categories:
            return f"Error: Invalid category '{category}'. Must be one of {valid_categories}."

        if not rule:
            return "Error: You must provide a 'rule' text for add/remove actions."

        current_rules = getattr(profile, category)

        # 2. Add rule
        if action == "add_rule":
            if rule not in current_rules:
                current_rules.append(rule)
                setattr(profile, category, current_rules)
                self.taste_engine.save_profile(profile)
                return f"Success: The rule '{rule}' has been permanently added to {category}."
            return "Notice: This rule already exists in the taste profile."

        # 3. Remove rule
        elif action == "remove_rule":
            if rule in current_rules:
                current_rules.remove(rule)
                setattr(profile, category, current_rules)
                self.taste_engine.save_profile(profile)
                return f"Success: The rule '{rule}' has been removed from {category}."
            return "Error: Rule not found in the specified category."

        else:
            return "Error: Invalid action. Use 'view', 'add_rule', or 'remove_rule'."

    def execute(self, action: str, category: Optional[str] = None, rule: Optional[str] = None) -> ToolResult:
        """Native engine execution entry point."""
        out = self.forward(action=action, category=category, rule=rule)
        success = not out.startswith("Error:")
        return ToolResult(
            success=success,
            stdout=out if success else "",
            stderr=out if not success else "",
            returncode=0 if success else 1,
            status="done" if success else "error",
        )
