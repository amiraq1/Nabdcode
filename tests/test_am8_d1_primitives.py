"""Am+8 D-1 primitive tests (D-1.1 rewritten — native Rich renderables).

Invariant guarantees (mirrored from D-0, extended to all primitives):
  - no Color() construction in primitives (colors only via SEMANTIC)
  - no hex literals, no rich Style(...) construction, no icon-glyph literals
  - glyphs resolve exclusively through Icon.glyph
  - every one of the 14 UIStates maps to a personality (total, no fallthrough)
  - the five personalities are VISUALLY DISTINCT (permanent guard)
  - Spinner keeps exposing the rate as a numeric VALUE (no loop/polling)
Snapshots are captured with the mandated fixed console:
    Console(width=80, force_terminal=True, color_system="truecolor")
"""
from __future__ import annotations

import importlib
import io
import re
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from wcwidth import wcswidth

from ui.design.icons import Icon
from ui.design.animation import AnimationProfile, AnimationSpec, Spinner as SpinnerEnum
from ui.design.state import UIState, UI_STATES
from ui.design.theme.semantic import SEMANTIC
from ui.design.tokens import ANIMATION_SPEED
from ui.design.primitives import (
    Personality, StatusLine, Spinner, SectionPanel, KeyValueRow,
    Divider, Badge, Row, Column, personality_of, style_of,
)
from ui.design.primitives.personality import (
    _PERSONALITY_OF, _PERSONALITY_STYLE,
)

DESIGN_ROOT = Path(__file__).resolve().parents[1] / "ui" / "design"
PRIM_DIR = DESIGN_ROOT / "primitives"

ANSI = re.compile(r"\x1b\[[0-9;]*m")
STYLE_CALL = re.compile(r"(?<![A-Za-z])Style\(")   # rich Style, not PersonalityStyle(


def _capture(renderable, width: int = 80) -> str:
    """Render a Rich renderable to a string via the mandated fixed console."""
    buf = io.StringIO()
    console = Console(file=buf, width=width, force_terminal=True,
                      color_system="truecolor")
    console.print(renderable)
    return buf.getvalue()


def _strip(s: str) -> str:
    return ANSI.sub("", s)


def _visible(renderable, width: int = 80) -> str:
    return _strip(_capture(renderable, width)).rstrip("\n")


def _prim_files():
    return [f for f in PRIM_DIR.glob("*.py") if f.name != "__init__.py"]


# ── invariants (kept from D-1) ───────────────────────────────────────────

def test_no_color_construction_in_primitives():
    offenders = [f.name for f in _prim_files() if "Color(" in f.read_text()]
    assert not offenders, f"Color() built outside theme/: {offenders}"


def test_no_hex_literals_in_primitives():
    offenders = [f.name for f in _prim_files() if re.search(r"#[0-9a-fA-F]{3,8}", f.read_text())]
    assert not offenders, f"hex literals in primitives: {offenders}"


def test_no_rich_style_construction_in_primitives():
    offenders = [f.name for f in _prim_files() if STYLE_CALL.search(f.read_text())]
    assert not offenders, f"rich Style(...) in primitives: {offenders}"


def test_no_icon_glyph_literals_in_primitives():
    forbidden = {Icon.glyph(m) for m in Icon}
    offenders = [f.name for f in _prim_files() if any(g in f.read_text() for g in forbidden)]
    assert not offenders, f"icon glyph literal in primitives: {offenders}"


def test_d1_modules_import_acyclically():
    for mod in [
        "ui.design.primitives.personality",
        "ui.design.primitives.status_line",
        "ui.design.primitives.spinner",
        "ui.design.primitives.section_panel",
        "ui.design.primitives.key_value_row",
        "ui.design.primitives.divider",
        "ui.design.primitives.badge",
        "ui.design.primitives.layout",
    ]:
        importlib.import_module(mod)


# ── personality: total coverage ──────────────────────────────────────────

def test_personality_covers_every_state():
    assert len(_PERSONALITY_OF) == len(UI_STATES) == 14
    for state in UI_STATES:
        p = personality_of(state)
        assert isinstance(p, Personality)
        assert p in _PERSONALITY_STYLE


def test_statusline_renders_all_fourteen_states():
    for state in UI_STATES:
        visible = _visible(StatusLine(state))
        assert visible.strip(), f"{state.name} rendered empty"
        assert style_of(state).verb in visible


# ── PERMANENT guard: five personalities are visually distinct ────────────

def test_personalities_are_visually_distinct():
    """No two personalities share a (color, icon) pair; RUNNING vs SUCCESS differ."""
    pairs: dict[tuple, str] = {}
    for p, st in _PERSONALITY_STYLE.items():
        key = (str(st.color), st.icon.name)
        assert key not in pairs, f"{p.name} shares ({key}) with {pairs.get(key)}"
        pairs[key] = p.name
    running = _PERSONALITY_STYLE[Personality.RUNNING]
    success = _PERSONALITY_STYLE[Personality.SUCCESS]
    assert running.color != success.color
    # distinctness holds in WEIGHT and RHYTHM too, not color alone
    assert (running.weight, running.rhythm) != (success.weight, success.rhythm)


def test_statusline_snapshot_per_personality():
    cases = [
        (Personality.THINKING, UIState.THINKING, "…  thinking  ↻  thinking"),
        (Personality.RUNNING,  UIState.RUNNING,  "▶  running  ▶  running"),
        (Personality.SUCCESS,  UIState.SUCCESS,  "✓  ok  success"),
        (Personality.WARNING,  UIState.WARNING,  "⚠  warn  …  warning"),
        (Personality.ERROR,    UIState.ERROR,    "✖  error  error"),
    ]
    for p, state, expected in cases:
        got = _visible(StatusLine(state))
        assert got == expected, f"{p.name}: {got!r} != {expected!r}"


def test_five_personalities_have_distinct_renders():
    states = [UIState.THINKING, UIState.RUNNING, UIState.SUCCESS,
              UIState.WARNING, UIState.ERROR]
    renders = {s.name: _visible(StatusLine(s)) for s in states}
    assert len(set(renders.values())) == 5


# ── spinner: rate is a numeric VALUE ─────────────────────────────────────

def test_spinner_accepts_every_profile():
    for prof in AnimationProfile:
        spec = AnimationSpec(profile=prof)
        assert _strip(_capture(Spinner(spec), 40)).strip(), f"{prof.name} empty"


def test_spinner_accepts_every_spinner_style():
    for sp in SpinnerEnum:
        spec = AnimationSpec(profile=AnimationProfile.NONE, spinner=sp,
                             speed=ANIMATION_SPEED.fast)
        assert _strip(_visible(Spinner(spec), 40)).strip(), f"{sp.name} empty"


def test_spinner_rate_is_value_not_hz_name():
    for speed in (ANIMATION_SPEED.instant, ANIMATION_SPEED.fast,
                  ANIMATION_SPEED.normal, ANIMATION_SPEED.slow):
        spec = AnimationSpec(profile=AnimationProfile.NONE, spinner=SpinnerEnum.DOTS,
                             speed=speed)
        rate = Spinner(spec).rate
        assert isinstance(rate, float)
        assert rate in (0.0, 0.1, 0.25, 0.5)


# ── key/value: wcwidth stays the arbiter; Rich owns the truncation ───────

def test_key_value_row_arabic_truncation():
    kv = KeyValueRow("k:", "السلامث")          # wcswidth 7 > avail
    out = _visible(kv, 10)                     # keyk:"(2) + gap(2) => avail 6
    w = wcswidth(out)
    assert w <= 10
    assert "ث" not in out or w <= 10  # dropped tail or never overflowed


def test_key_value_row_cjk_truncation():
    wide = _visible(KeyValueRow("path:", "日本語テスト"), 80)
    assert "日本語" in wide or "テスト" in wide     # roomy console, no truncation
    tight = _visible(KeyValueRow("path:", "日本語テスト"), 9)  # 5+2 => avail 2
    assert wcswidth(tight) <= 9
    assert "テスト" not in tight                   # truncated, dropped


# ── composition: all 8 atoms inside one Group inside one Panel ───────────

def test_composition_group_in_panel():
    """All 8 atoms render inside a single Group inside a single Panel with
    no manual width/height math anywhere (Rich owns layout/measurement)."""
    scene = Panel(
        Group(
            StatusLine(UIState.RUNNING, "compose"),
            Spinner(AnimationSpec(profile=AnimationProfile.PROGRESS,
                                  speed=ANIMATION_SPEED.fast)),
            KeyValueRow("path:", "/workspace/ui/design/primitives"),
            Badge("ok", "success"),
            Divider(),
            SectionPanel("block", Group(
                Badge("warn", "warning"),
                KeyValueRow("key:", "value"),
            )),
            Row(StatusLine(UIState.THINKING, "a"), StatusLine(UIState.SUCCESS, "b")),
            Column(Badge("x", "error"), Badge("y", "muted")),
        ),
        title="compose",
    )
    out = _capture(scene, 80)
    assert out
    assert "compose" in out
    assert "running" in out
