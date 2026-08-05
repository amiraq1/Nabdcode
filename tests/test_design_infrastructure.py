"""Am+8 D-0 infrastructure invariant tests.

These pin the guarantees D-0 delivers and must keep holding:
  - single source of truth (no raw-color construction outside theme/)
  - immutable token values
  - complete state/ icon / typography / layout registries
  - abstract widget contracts (cannot be instantiated directly)
  - acyclic imports (a successful import proves no cycle)
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import ui.design as D
from ui.design.theme import Color, SemanticTheme, SEMANTIC
from ui.design.tokens import SPACING, GAP, RADIUS, ELEVATION, DENSITY, PROGRESS_DENSITY, ANIMATION_SPEED, SCALE
from ui.design.icons import Icon
from ui.design.animation import AnimationProfile, Spinner, AnimationSpec
from ui.design.typography import TypographyPreset, PRESETS
from ui.design.layout import Layout, LAYOUT
from ui.design.state import UIState, StateRecord, UI_STATES, state_of
from ui.design.primitives import Widget
from ui.design.contracts import (
    StatusWidget, ToolWidget, PanelWidget, CardWidget, ListWidget,
    DialogWidget, FooterWidget, HeaderWidget, ProgressWidget, SpinnerWidget,
)

DESIGN_ROOT = Path(__file__).resolve().parents[1] / "ui" / "design"


# ── acyclic imports ─────────────────────────────────────────────────────

def test_no_circular_imports():
    """Importing every leaf submodule succeeds (proves no import cycle)."""
    for mod in [
        "ui.design", "ui.design.theme", "ui.design.theme.color",
        "ui.design.theme.semantic", "ui.design.tokens", "ui.design.tokens.spacing",
        "ui.design.tokens.sizing", "ui.design.icons", "ui.design.icons.registry",
        "ui.design.animation", "ui.design.animation.profiles",
        "ui.design.typography", "ui.design.typography.presets",
        "ui.design.layout", "ui.design.layout.constants",
        "ui.design.state", "ui.design.state.ui_state",
        "ui.design.primitives", "ui.design.primitives.widget",
        "ui.design.contracts", "ui.design.contracts.widgets",
    ]:
        importlib.import_module(mod)


# ── single source of truth ──────────────────────────────────────────────

def test_raw_colors_only_in_theme_owner():
    """Color(...) literals must only be constructed inside ui/design/theme/."""
    offenders = []
    for f in DESIGN_ROOT.rglob("*.py"):
        if "theme/" not in str(f.relative_to(DESIGN_ROOT)) and f.name == "__init__.py":
            continue
        rel = str(f.relative_to(DESIGN_ROOT))
        if rel.startswith("theme"):
            continue
        text = f.read_text()
        if "Color(" in text:
            offenders.append(rel)
    assert not offenders, f"Color() constructed outside theme/: {offenders}"


def test_semantic_theme_has_every_category():
    required = {
        "background", "surface", "panel", "header", "footer", "border",
        "text", "text_muted", "text_dim", "caption", "code",
        "primary", "primary_dim", "secondary", "accent",
        "success", "warning", "danger", "error", "info",
        "thinking", "running", "idle", "selection", "focus", "disabled",
    }
    missing = required - set(SemanticTheme.__dataclass_fields__)
    assert not missing, f"SemanticTheme missing categories: {missing}"
    for name in required:
        c = getattr(SEMANTIC, name)
        assert isinstance(c, Color), f"{name} is not a Color"


# ── immutability ────────────────────────────────────────────────────────

def test_color_is_immutable():
    c = Color("#0891b2")
    with pytest.raises(Exception):
        c.hex = "#123456"  # frozen dataclass rejects mutation
    # semantic theme Color fields are immutable too
    with pytest.raises(Exception):
        SEMANTIC.primary.hex = "#123456"


# ── registries complete ─────────────────────────────────────────────────

def test_icon_registry_nonempty():
    required = {"SUCCESS", "WARNING", "ERROR", "THINKING", "RUNNING", "IDLE",
                "FOLDER", "FILE", "GIT", "DIFF", "MEMORY", "SEARCH",
                "EDIT", "DELETE", "STOP", "RESUME", "CANCEL", "INFO"}
    have = {m.name for m in Icon}
    assert required <= have, f"missing icons: {required - have}"


def test_animation_profiles_complete():
    assert {"NONE", "SUBTLE", "THINKING", "STREAMING", "PULSE", "BLINK",
            "PROGRESS", "TRANSITION"} <= {p.name for p in AnimationProfile}
    assert {"NONE", "DOTS", "LINE", "ELAPSE", "PULSE", "WAVE", "BRAILLE"} <= {s.name for s in Spinner}


def test_typography_presets_complete():
    required = {"terminal_title", "section_title", "normal", "muted", "caption",
                "code", "success", "warning", "danger", "thinking", "running", "error"}
    assert set(PRESETS) == required
    for p in PRESETS.values():
        assert isinstance(p, TypographyPreset)
        assert p.color is not None


def test_layout_constants_positive():
    for name in ("header_height", "footer_height", "status_bar_height",
                 "sidebar_width", "panel_min_width", "min_content_width"):
        assert getattr(LAYOUT, name) > 0


def test_state_registry_complete():
    assert len(UI_STATES) == len(UIState), "every UIState must have a record"
    for rec in UI_STATES.values():
        assert isinstance(rec, StateRecord)
        assert isinstance(rec.color, Color)
        assert isinstance(rec.icon, Icon)
        assert isinstance(rec.spinner, Spinner)
        assert isinstance(rec.animation_profile, AnimationProfile)
        assert isinstance(rec.priority, int)
        assert Icon.glyph(rec.icon)  # non-empty glyph


# ── abstract contracts ──────────────────────────────────────────────────

def test_widget_and_contracts_are_abstract():
    for cls in (Widget, StatusWidget, ToolWidget, PanelWidget, CardWidget,
                ListWidget, DialogWidget, FooterWidget, HeaderWidget,
                ProgressWidget, SpinnerWidget):
        assert cls.__abstractmethods__, f"{cls.__name__} must be abstract"
        with pytest.raises(TypeError):
            cls()  # type: ignore[abstract]


def test_state_of_resolves():
    assert state_of(UIState.SUCCESS).state is UIState.SUCCESS
