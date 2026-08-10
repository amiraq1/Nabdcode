"""BRAND-3: tests for minimal-dark identity.

ع1 minimal_header_only_mark   — الترويسة الافتراضية: ◈ و agent؛ لا █، لا Repo:
ع2 dark_toolbar_no_white      — الشريط السفلي يأخذ نمطاً داكناً من SEMANTIC
ع3 indicator_foreground_not_fill — إطارات المؤشر: brand كأمامية لا خلفية معبأة
ع4 classic_preserved          — render_logo("classic") يحتوي █  (يجب أن يكون أخضر)
"""
import importlib
import inspect
import io
import sys
import types


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _capture_draw(mode=None):
    """Call nabd_logo.draw / render_logo and return captured Rich output."""
    from io import StringIO
    from rich.console import Console

    mod = importlib.import_module("nabd_logo")

    buf = StringIO()
    fake_console = Console(file=buf, force_terminal=False, color_system=None)
    # Monkey-patch the module console temporarily
    orig = mod.console
    mod.console = fake_console
    try:
        if mode is None:
            mod.draw()
        else:
            # render_logo is the new function introduced by BRAND-3
            mod.render_logo(mode)
    finally:
        mod.console = orig
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ع1 — minimal header contains only ◈ and agent — no █, no Repo:
# ---------------------------------------------------------------------------
def test_minimal_header_only_mark():
    out = _capture_draw()          # default / minimal mode
    assert "◈" in out, "default draw() must contain ◈"
    assert "agent" in out, "default draw() must contain 'agent'"
    assert "█" not in out, "default draw() must NOT contain ASCII blocks (█)"
    assert "Repo:" not in out, "default draw() must NOT contain 'Repo:'"


# ---------------------------------------------------------------------------
# ع2 — dark toolbar: PromptSession receives a style with bottom-toolbar dark
# ---------------------------------------------------------------------------
def test_dark_toolbar_no_white():
    src = inspect.getsource(importlib.import_module("main"))
    # Must reference bottom-toolbar styling routed through SEMANTIC
    assert "bottom-toolbar" in src, (
        "main.py must define a 'bottom-toolbar' style token"
    )
    assert "SEMANTIC" in src, "main.py must use SEMANTIC for toolbar colour"


# ---------------------------------------------------------------------------
# ع3 — indicator frames use brand as foreground — no "on <bg>" fill
# ---------------------------------------------------------------------------
def test_indicator_foreground_not_fill():
    from ui.cc_style import typing_indicator_frames
    from ui.design.theme.semantic import SEMANTIC

    frames = typing_indicator_frames()
    assert len(frames) > 0, "must have at least one frame"
    for frame in frames:
        rendered = str(frame)
        # The style must not contain "on " (background fill)
        for span in frame._spans:
            assert " on " not in str(span.style), (
                f"indicator frame style '{span.style}' must not contain ' on ' (background fill)"
            )
        # Must contain brand colour somewhere in the style
        brand_val = str(SEMANTIC.brand)
        styles_present = [str(s.style) for s in frame._spans]
        assert any(brand_val in st for st in styles_present), (
            f"indicator frame must reference brand colour {brand_val!r}"
        )


# ---------------------------------------------------------------------------
# ع4 — classic mode preserved (must contain █) — should be GREEN now
# ---------------------------------------------------------------------------
def test_classic_preserved():
    out = _capture_draw("classic")   # render_logo("classic")
    assert "█" in out, "render_logo('classic') must still contain █ blocks"
