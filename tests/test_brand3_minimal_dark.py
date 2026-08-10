"""BRAND-3 → BRAND-4: عقود محدثة بتغيير موثق.

BRAND-4 يُعيد الكلاسيكي افتراضياً؛ لا toolbar؛ دوال المؤشر تبقى نقية
في cc_style بلا توصيل.

ع1 classic_is_now_default     — draw() يحتوي █ و Repo: (BRAND-4)
ع2 dark_toolbar_removed       — main.py لا يحتوي bottom-toolbar بعد الآن
ع3 indicator_foreground_not_fill — دوال المؤشر في cc_style نقية: brand أمامية لا خلفية
ع4 classic_via_render_logo    — render_logo("classic") يحتوي █ (محفوظ)
"""
import importlib
import inspect


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _capture_draw(mode=None):
    """Run nabd_logo.draw / render_logo and return captured output."""
    from io import StringIO
    from rich.console import Console

    mod = importlib.import_module("nabd_logo")
    buf = StringIO()
    fake_console = Console(file=buf, force_terminal=False, color_system=None)
    orig = mod.console
    mod.console = fake_console
    try:
        if mode is None:
            mod.draw()
        else:
            mod.render_logo(mode)
    finally:
        mod.console = orig
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ع1 — BRAND-4: draw() default is classic (█ + Repo:)
# ---------------------------------------------------------------------------
def test_classic_is_now_default():
    """BRAND-4 supersedes BRAND-3 minimal: draw() is now classic again."""
    out = _capture_draw()
    assert "█" in out, "BRAND-4: draw() must output classic ASCII blocks (█)"
    assert "Repo:" in out, "BRAND-4: draw() must output 'Repo:' metadata"


# ---------------------------------------------------------------------------
# ع2 — dark toolbar removed: main.py has no bottom-toolbar token
# ---------------------------------------------------------------------------
def test_dark_toolbar_removed():
    """BRAND-4: toolbar machinery removed — no bottom-toolbar in main.py."""
    src = inspect.getsource(importlib.import_module("main"))
    assert "bottom-toolbar" not in src, (
        "BRAND-4: 'bottom-toolbar' style token must be removed from main.py"
    )
    assert "bottom_toolbar" not in src, (
        "BRAND-4: bottom_toolbar= kwarg must be removed from main.py"
    )


# ---------------------------------------------------------------------------
# ع3 — indicator frames in cc_style: brand as foreground, no "on <bg>"
# ---------------------------------------------------------------------------
def test_indicator_foreground_not_fill():
    """دوال المؤشر في cc_style تبقى نقية: brand أمامية لا خلفية معبأة."""
    from ui.cc_style import typing_indicator_frames
    from ui.design.theme.semantic import SEMANTIC

    frames = typing_indicator_frames()
    assert len(frames) > 0, "must have at least one frame"
    for frame in frames:
        for span in frame._spans:
            assert " on " not in str(span.style), (
                f"indicator frame style '{span.style}' must not contain ' on '"
            )
        brand_val = str(SEMANTIC.brand)
        styles_present = [str(s.style) for s in frame._spans]
        assert any(brand_val in st for st in styles_present), (
            f"indicator frame must reference brand colour {brand_val!r}"
        )


# ---------------------------------------------------------------------------
# ع4 — classic preserved via render_logo("classic")
# ---------------------------------------------------------------------------
def test_classic_via_render_logo():
    out = _capture_draw("classic")
    assert "█" in out, "render_logo('classic') must still contain █ blocks"
