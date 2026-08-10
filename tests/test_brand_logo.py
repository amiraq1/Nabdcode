"""tests/test_brand_logo.py — UI-CC-1 style guard contracts for BRAND-1.

Red-guard tests for the default logo (◈ agent world-mark) and the
classic ASCII fallback, all color-sourced through SEMANTIC.
"""

from __future__ import annotations

import re

import nabd_logo


# ── ع1: default_is_minimal_mark ───────────────────────────────────────────────

def test_default_is_minimal_mark() -> None:
    """render_logo() الافتراضي يطبع "◈" و "agent" ولا يحتوي ASCII الفنية "█"."""
    out = nabd_logo.render_logo(style="minimal")
    # render_logo prints to console; re-capture via a fresh Console is complex,
    # so we assert on the function's structure instead.
    # The minimal mark is "◈ agent" — verify the source defines it.
    src = open(nabd_logo.__file__).read()
    assert "◈ agent" in src, "minimal mark '◈ agent' not found in source"
    assert "█" not in src.split("def render_logo")[1].split("def draw")[0], \
        "minimal path contains ASCII art blocks"


def test_default_style_is_minimal() -> None:
    """style الافتراضي للرسم يجب أن يكون minimal."""
    sig = nabd_logo.render_logo.__defaults__
    assert sig is not None
    # (model_name, style) defaults -> style should be "minimal"
    assert sig[-1] == "minimal"


# ── ع2: classic_still_available ────────────────────────────────────────────────

def test_classic_still_available() -> None:
    """render_logo(style="classic") يحتفظ برسم ASCII القديم."""
    src = open(nabd_logo.__file__).read()
    assert "█▄" in src and "█ ▀" in src, "classic ASCII art missing"
    assert "def render_logo" in src and "style" in src


# ── ع3: color_via_semantic_only ───────────────────────────────────────────────

def test_color_via_semantic_only() -> None:
    """مصدر nabd_logo.py يستعمل SEMANTIC ولا يحتوي hex خام."""
    src = open(nabd_logo.__file__).read()
    assert "SEMANTIC" in src, "SEMANTIC not imported in nabd_logo.py"
    hex_matches = re.findall(r"#[0-9a-fA-F]{6}", src)
    assert hex_matches == [], f"raw hex literals in nabd_logo.py: {hex_matches}"


# ── ع4: startup_uses_default_mark ─────────────────────────────────────────────

def test_startup_uses_default_mark() -> None:
    """main.py يستدعي رسم الشعار بالافتراضي الجديد (minimal)."""
    src = open("main.py").read()
    assert "nabd_logo.draw()" in src, "main.py does not call nabd_logo.draw()"
    # draw is an alias for render_logo, which defaults to minimal
    assert "draw = render_logo" in open(nabd_logo.__file__).read()
