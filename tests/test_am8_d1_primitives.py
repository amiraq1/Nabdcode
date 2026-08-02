"""Am+8 D-1 primitive tests (D-1.1 rewritten — native Rich renderables).

Invariant guarantees (mirrored from D-0, extended to all primitives):
  - no Color() construction in primitives (colors only via SEMANTIC)
  - no hex literals, no rich Style(...) construction, no icon-glyph literals
  - glyphs resolve exclusively through Icon.glyph
  - every one of the 14 UIStates maps to a personality (total, no fallthrough)
  - the five personalities are VISUALLY DISTINCT (permanent guard)
  - Spinner keeps exposing the rate as a numeric VALUE (no loop/polling)
Snapshots are captured with the mandated fixed console (width and height
both pinned — a width-only console falls back to the real terminal):
"""
from __future__ import annotations

import importlib
import io
import re
import pytest
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
    """Render a Rich renderable to a string via the mandated fixed console.

    IMPORTANT: a console with width=N only honors N when height is also
    supplied. Rich's size property requires both _width and _height to be
    non-None; otherwise it falls through to the real terminal dimensions
    (80x25 on Termux even when width=9 is requested). Always pass height=25.
    """
    buf = io.StringIO()
    console = Console(file=buf, width=width, height=25, force_terminal=True,
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
        (Personality.THINKING, UIState.THINKING, "\u2026  thinking  thinking"),
        (Personality.RUNNING,  UIState.RUNNING,  "\u25b6  running  running"),
        (Personality.SUCCESS,  UIState.SUCCESS,  "✓  ok  success"),
        (Personality.WARNING,  UIState.WARNING,  "⚠  warn  warning"),
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


# ── icons: COLLAPSE keeps a distinct glyph ────────────────────────────────

def test_icon_collapse_is_distinct_glyph():
    """COLLAPSE (►, U+25BA) must be a distinct member — never folded into
    RUNNING (▶) or RESUME (▸), so the collapse affordance survives."""
    glyph = Icon.glyph(Icon.COLLAPSE)
    assert glyph == "\u25ba"
    siblings = {Icon.glyph(m) for m in Icon if m is not Icon.COLLAPSE}
    assert glyph not in siblings


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

def test_row_lays_out_horizontally():
    """Row must compose children on ONE line (atoms carry faithful
    __rich_measure__; without it Rich Columns assumes full width and stacks
    items vertically)."""
    row = Row(StatusLine(UIState.SUCCESS, "clean"), Badge("SHELL", "info"))
    out = _visible(row)
    lines = out.splitlines()
    assert len(lines) == 1
    assert Icon.glyph(Icon.SUCCESS) in lines[0]
    assert "[SHELL]" in lines[0]
    assert lines[0].endswith("[SHELL]")


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


# ── D-2: theme swap seam + structural equality + widget style guard ───────

MIGRATED_WIDGETS = [
    Path(__file__).resolve().parents[1] / "ui" / "widgets" / "tool_result.py",
    Path(__file__).resolve().parents[1] / "ui" / "widgets" / "status_bar.py",
]
REPO_ROOT = MIGRATED_WIDGETS[0].parents[2]

_THEME_DEPENDENTS = [
    "ui.design.typography.presets",   # bakes SEMANTIC into PRESETS at import
    "ui.design.typography",           # re-exports PRESETS
    "ui.design.primitives.personality",
    "ui.design.primitives.status_line",
    "ui.design.primitives.badge",
    "ui.design.primitives.key_value_row",
    "ui.design.primitives.divider",
    "ui.design.primitives.section_panel",
    "ui.design.primitives.spinner",
    "ui.design.primitives.layout",
    "ui.design.primitives",           # package __init__ rebinds all atoms
    "ui.widgets.tool_result",
    "ui.widgets.status_bar",
]


def _plain_render(widget, width: int = 80) -> str:
    """Render a widget and strip ALL ANSI, returning pure structure bytes."""
    from ui.widgets.tool_result import ToolResultWidget
    from rich.console import Console
    buf = io.StringIO()
    console = Console(file=buf, width=width, height=25, force_terminal=True,
                      color_system="truecolor")
    widget._console = console
    console.print(widget.render())
    return ANSI.sub("", buf.getvalue())


def test_theme_swap_requires_no_widget_change():
    """D-0 seam proof: swapping SEMANTIC changes COLORS (ANSI) while the
    ANSI-stripped structure stays byte-identical — and the widget file is
    never touched. If a palette swap needed a widget edit, D-0 is wrong.

    Runs each palette in a FRESH subprocess interpreter: importlib.reload
    mutates module globals in place, so an in-process swap would leak new
    class objects into every previously-imported binding (pytest-randomly
    exposes that as order-dependent failures). The subprocess isolates the
    swap to the child.
    """
    import dataclasses
    import subprocess
    import sys

    swap_block = (
        'm.SEMANTIC = dataclasses.replace(DEFAULT, success=Color("#00ff00"),\n'
        "                                 error=Color(\"#ff0000\"),\n"
        "                                 selection=Color(\"#00ffff\"),\n"
        "                                 accent=Color(\"#ff00ff\"),\n"
        "                                 thinking=Color(\"#ffff00\"),\n"
        "                                 text_muted=Color(\"#888888\"),\n"
        "                                 text=Color(\"#ffffff\"))\n"
        f"for name in {_THEME_DEPENDENTS!r}:\n"
        "    if name in sys.modules:\n"
        "        importlib.reload(sys.modules[name])\n"
    )

    def run(swap: bool, wfile: Path, wmod: str, class_name: str, inst_code: str) -> str:
        child_template = f"""\
import sys, io, importlib, dataclasses
sys.path.insert(0, {{root!r}})
from {wmod} import {class_name}
import ui.design.theme.semantic as m
from ui.design.theme.semantic import SEMANTIC as DEFAULT
from ui.design.theme.color import Color
from rich.console import Console
{{swap_code}}
import {wmod}
w = {wmod}.{class_name}({inst_code})
buf = io.StringIO()
c = Console(file=buf, width=80, height=25, force_terminal=True, color_system="truecolor")
w._console = c
if hasattr(w, 'render'):
    renderable = w.render()
elif hasattr(w, '_build_renderable'):
    renderable = w._build_renderable()
else:
    renderable = w
c.print(renderable)
sys.stdout.write(buf.getvalue())
"""
        code = child_template.format(root=str(REPO_ROOT),
                                     swap_code=swap_block if swap else "")
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    widget_cases = [
        (MIGRATED_WIDGETS[0], "ui.widgets.tool_result", "ToolResultWidget", '"shell", "ls output\\nsecond line"'),
        (MIGRATED_WIDGETS[1], "ui.widgets.status_bar", "AgentStatusBar", ""),
    ]

    for wfile, wmod, class_name, inst_code in widget_cases:
        source_before = wfile.read_text()
        ansi_default = run(False, wfile, wmod, class_name, inst_code)
        ansi_swapped = run(True, wfile, wmod, class_name, inst_code)

        assert ansi_default != ansi_swapped                      # colors changed
        assert ANSI.sub("", ansi_default) == ANSI.sub("", ansi_swapped)  # structure identical
        assert wfile.read_text() == source_before         # widget never touched


def test_migrated_widget_carries_no_color_literals():
    """D-2 style guard: the migrated widget file carries no hex literals,
    no Rich color names, and no Style( / style="…" string literals — every
    color resolves through SEMANTIC (swap seam stays at the theme layer)."""
    for wfile in MIGRATED_WIDGETS:
        src = wfile.read_text()

        hex_lit = re.findall(r"#[0-9a-fA-F]{3,8}", src)
        assert not hex_lit, f"hex literals in {wfile.name}: {hex_lit}"

        names = re.findall(
            r"\b(?:cyan|magenta|violet|green|red|yellow|blue|white|black|"
            r"grey|gray|bright_[a-z]+)\b",
            src, re.IGNORECASE,
        )
        assert not names, f"rich color names in {wfile.name}: {names}"

        style_lit = re.findall(r"Style\(|style\s*=\s*['\"]", src)
        assert not style_lit, f"rich Style construction in {wfile.name}: {style_lit}"


def test_success_error_share_skeleton():
    """D-2 structural equality: SUCCESS and ERROR renders share a
    byte-identical ANSI-stripped skeleton after normalizing icon glyph and
    verb; only color/icon/weight differ. Declared exception: ERROR may add
    a named optional 'reason' segment — modeled first-class, never hidden."""
    from ui.widgets.tool_result import ToolResultWidget

    ok = ToolResultWidget("shell", "", success=True)
    err = ToolResultWidget("shell", "", success=False)

    def norm(s: str) -> str:
        s = (s.replace(Icon.glyph(Icon.SUCCESS), "O")
              .replace(Icon.glyph(Icon.ERROR), "O")
              .replace("ok", "V")
              .replace("error", "V"))
        # collapse width-fill whitespace runs (Rich pads every row to the
        # panel width); the skeleton comparison ignores fill, not tokens
        return re.sub(r" +", " ", s).strip()

    a, b = _plain_render(ok), _plain_render(err)
    assert norm(a) == norm(b), f"skeleton differs:\n{norm(a)!r}\n{norm(b)!r}"

    # Declared exception: ERROR may carry an explicit reason segment
    err2 = ToolResultWidget("shell", "", success=False, summary="boom")
    b2 = _plain_render(err2)
    assert "reason" in b2 and "boom" in b2
    b2_no_reason = "\n".join(l for l in b2.splitlines() if "reason" not in l)
    assert norm(a) == norm(b2_no_reason)

def test_status_line_hide_verb():
    """D-3: StatusLine can hide its verb for compact rendering."""
    from ui.design.primitives.status_line import StatusLine
    from ui.design.state import UIState
    from ui.design.icons import Icon
    
    # Normal: icon + gap + verb + gap + context
    normal = StatusLine(UIState.SUCCESS, "Thinking")
    normal_text = _visible(normal, 80)
    assert "ok" in normal_text
    assert "Thinking" in normal_text
    
    # Hidden verb: icon + gap + context
    compact = StatusLine(UIState.SUCCESS, "Thinking", hide_verb=True)
    compact_text = _visible(compact, 80)
    assert "ok" not in compact_text
    assert "Thinking" in compact_text

@pytest.mark.parametrize("state", list(UIState))
def test_status_line_emits_exactly_one_leading_glyph(state):
    from ui.design.primitives.status_line import StatusLine
    from ui.design.tokens import GAP
    
    sl = StatusLine(state, "Ctx", hide_verb=False)
    rendered = _visible(sl, 80)
    
    gap = " " * GAP.status
    parts = rendered.split(gap)
    
    # Should be exactly 3 parts: glyph, verb, context
    assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}: {parts}"
    assert len(parts[0]) == 1, f"Expected exactly one leading glyph, got {len(parts[0])}: {parts[0]!r}"
    assert parts[2] == "Ctx"

@pytest.mark.parametrize("state", list(UIState))
def test_static_render_uses_state_icon_not_spinner_frame(state):
    from ui.design.primitives.status_line import StatusLine
    from ui.design.icons import Icon
    from ui.design.primitives.personality import style_of, UI_STATES
    from ui.design.tokens import GAP
    from ui.design.animation import Spinner

    sl = StatusLine(state, "Ctx", hide_verb=False)
    rendered = _visible(sl, 80)
    gap = " " * GAP.status
    leading_glyph = rendered.split(gap)[0]

    style = style_of(state)
    expected_icon = Icon.glyph(style.icon)
    
    assert leading_glyph == expected_icon
    
    spinner = UI_STATES[state].spinner
    if spinner != Spinner.NONE:
        assert leading_glyph != spinner.frame


# ── design global mutation guard ─────────────────────────────────────────────

def test_no_test_mutates_shared_design_globals():
    """Permanent guard: the shared design globals must equal their pristine values.

    Any test that hot-reloads or monkey-patches _PERSONALITY_STYLE,
    _PERSONALITY_OF, or Icon must restore them. This guard catches the leak
    by comparing current state against a fresh import in a subprocess so that
    in-process mutations don't poison the comparison itself.
    """
    import subprocess, sys
    script = """
import sys, json
sys.path.insert(0, sys.argv[1])
from ui.design.primitives.personality import _PERSONALITY_OF, _PERSONALITY_STYLE
from ui.design.icons import Icon as _Icon
result = {
    "personality_of_keys": sorted(str(k) for k in _PERSONALITY_OF),
    "personality_of_values": sorted(str(v) for v in _PERSONALITY_OF.values()),
    "personality_style_keys": sorted(str(k) for k in _PERSONALITY_STYLE),
    "icon_members": sorted(str(m) for m in _Icon),
}
import sys
import json
sys.stdout.write(json.dumps(result))
"""
    import json
    root = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", script, root],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    pristine = json.loads(result.stdout)

    # Compare against the in-process (possibly mutated) state
    current_of_keys = sorted(str(k) for k in _PERSONALITY_OF)
    current_of_values = sorted(str(v) for v in _PERSONALITY_OF.values())
    current_style_keys = sorted(str(k) for k in _PERSONALITY_STYLE)
    from ui.design.icons import Icon as _Icon
    current_icon_members = sorted(str(m) for m in _Icon)

    assert current_of_keys == pristine["personality_of_keys"], (
        "_PERSONALITY_OF keys mutated by a test"
    )
    assert current_of_values == pristine["personality_of_values"], (
        "_PERSONALITY_OF values mutated by a test"
    )
    assert current_style_keys == pristine["personality_style_keys"], (
        "_PERSONALITY_STYLE keys mutated by a test"
    )
    assert current_icon_members == pristine["icon_members"], (
        "Icon registry mutated by a test"
    )


# ── D-3b: no unpinned Console in the test tree ──────────────────────────────

_UNPINNED_CONSOLE_ALLOWLIST = {
    # TEMPORARY — emptied by the follow-up commit (debt ledger, not exemption)
    "tests/test_status_bar_live.py",
    "tests/test_keybindings.py",
    "tests/test_tool_result_widget.py",
    "tests/test_tool_result_list.py",
}


def _console_calls(src: str) -> list[str]:
    """Extract full Console( … ) call texts, spanning multiple lines."""
    calls: list[str] = []
    i = 0
    while True:
        j = src.find("Console(", i)
        if j == -1:
            break
        depth = 0
        k = j + len("Console(") - 1
        while k < len(src):
            if src[k] == "(":
                depth += 1
            elif src[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        calls.append(src[j:k + 1])
        i = k + 1
    return calls


def test_no_unpinned_console_in_tests():
    """Every console built with width= in the test tree must also pin
    height=…; a bare width falls through to the real terminal dimensions
    (80x25 on Termux) and silently un-measures the snapshot. Tolerated hits
    may only live in the TEMPORARY allow-list above: adding a new file to it
    in any future commit is forbidden — the guard's job is to block NEW
    unpinned sites, and the follow-up commit empties the list."""
    tests_root = Path(__file__).resolve().parents[1] / "tests"
    offenders: dict[str, list[str]] = {}
    for path in sorted(tests_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        src = path.read_text()
        rel = path.relative_to(tests_root.parent).as_posix()
        for call in _console_calls(src):
            if "width=" in call and "height=" not in call:
                offenders.setdefault(rel, []).append(" ".join(call.split())[:90])
    unexpected = {
        rel: sites for rel, sites in offenders.items()
        if rel not in _UNPINNED_CONSOLE_ALLOWLIST
    }
    assert not unexpected, f"console width= without height=:\n{unexpected}"
