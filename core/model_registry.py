# core/model_registry.py
"""
High-Fidelity Model Registry & Badge Presentation Metadata Module.

Architectural DNA inspired by professional model registry breakdowns (Kt / The Badges):
  1. Orthogonal Metadata Flags: Decouples presentational badges (badge: "free") from
     visibility controls (hidden: bool) and vendor labels.
  2. Single Source of Truth (DRY Helper): Replaces duplicated literal checks with
     centralized is_free_model() inspection.
  3. Formatting Helpers: Standardized selector label layout (with FREE / default tags
     and column alignment) and short name generators.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ModelEntry:
    id: str
    name: str
    badge: Optional[str] = None       # e.g., "free", "pro", "beta"
    hidden: bool = False              # Orthogonal visibility flag
    vendor_label: str = ""


def is_free_model(model: ModelEntry) -> bool:
    """DRY helper: returns True if model entry has the 'free' badge."""
    return model.badge == "free"


def format_model_selector_label(
    model: ModelEntry,
    default_id: Optional[str] = None,
    col_width: int = 32,
) -> str:
    """
    Format model label for list pickers with column alignment padding and badges.
    Appends ' (FREE)' for free models and ' (default)' if model matches default_id.
    """
    badge_str = " (FREE)" if is_free_model(model) else ""
    default_str = " (default)" if default_id and model.id == default_id else ""

    base_len = len(model.name) + len(badge_str)
    padding = " " * max(0, col_width - base_len)

    return f"{model.name}{badge_str}{padding}{default_str}".rstrip()


def get_model_short_name(model: ModelEntry) -> str:
    """Return slugified/short display name annotated with (free) if applicable."""
    suffix = " (free)" if is_free_model(model) else ""
    return f"{model.name}{suffix}"


# Centralized Registry of Models
MODEL_REGISTRY: Dict[str, ModelEntry] = {
    "MiniMaxAI/MiniMax-M3-Free": ModelEntry(
        id="MiniMaxAI/MiniMax-M3-Free",
        name="MiniMax M3 Free",
        badge="free",
        hidden=True,
    ),
    "tencent/Hy3": ModelEntry(
        id="tencent/Hy3",
        name="Tencent Hy3",
        badge="free",
        hidden=False,
    ),
    "google/gemma-2-9b-it": ModelEntry(
        id="google/gemma-2-9b-it",
        name="Google Gemma 2 9B",
        badge="free",
        hidden=False,
    ),
}


def get_visible_models() -> List[ModelEntry]:
    """Return all non-hidden models in the registry."""
    return [m for m in MODEL_REGISTRY.values() if not m.hidden]
