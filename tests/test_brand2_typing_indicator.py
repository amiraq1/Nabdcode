"""tests/test_brand2_typing_indicator.py — BRAND-2 red-guard tests.

Verifies the typing-indicator contract:
  • The indicator mark is "◈ agent" rendered in SEMANTIC.brand color
    (no raw #hex in cc_style).
  • Multiple animation frames exist (>=2 visually distinct styles).
  • The startup logo is the NABDCODE ASCII banner (post-revert).
  • main.py wires the animated indicator + invalidate() into the prompt.

Uses ``getattr`` with a sentinel so the module collects even before the
functions exist — individual tests then report RED cleanly.
"""

from __future__ import annotations

import inspect

from ui.design.theme.semantic import SEMANTIC
import ui.cc_style as cc
import nabd_logo
import main

# Sentinel: functions may not exist yet (red phase).
typing_indicator_frames = getattr(cc, "typing_indicator_frames", None)
typing_indicator_frame = getattr(cc, "typing_indicator_frame", None)


class TestBrand2TypingIndicator:
    # ── ع1: indicator_mark_and_brand_color ────────────────────────────────

    def test_indicator_mark_and_brand_color(self):
        """typing_indicator_frame(0) → Text يحتوي '◈' و 'agent' بنمط brand."""
        assert typing_indicator_frame is not None, "typing_indicator_frame not implemented"
        frame = typing_indicator_frame(0)
        assert "◈" in frame.plain
        assert "agent" in frame.plain
        # Style must route through SEMANTIC.brand — no raw hex in cc_style.
        src = inspect.getsource(cc)
        assert "#00ff9d" not in src, "cc_style must not embed raw brand hex"

    # ── ع2: animation_frames_differ ─────────────────────────────────────────

    def test_animation_frames_differ(self):
        """typing_indicator_frames() >= إطارين مختلفين بصرياً."""
        assert typing_indicator_frames is not None, "typing_indicator_frames not implemented"
        frames = typing_indicator_frames()
        assert len(frames) >= 2, f"need >=2 frames, got {len(frames)}"
        styles = set()
        for f in frames:
            # Rich Span is a 3-field namedtuple: (start, end, style)
            for _start, _end, style in f.spans:
                styles.add(str(style))
        assert len(styles) >= 2, f"need >=2 distinct styles, got {len(styles)}: {styles}"

    # ── ع3: startup_logo_is_ascii ───────────────────────────────────────────

    def test_startup_logo_is_ascii(self):
        """BRAND-4: draw() الافتراضي يُخرج الكلاسيكي (█ + Repo:).

        BRAND-4 يُعيد الكلاسيكي افتراضياً — _draw_classic هو الهدف.
        render_logo("classic") محفوظ؛ _draw_minimal متاح غير موصول.
        """
        import inspect
        src = inspect.getsource(nabd_logo.draw)
        # BRAND-4: draw() delegates to _draw_classic
        assert "_draw_classic" in src, (
            "BRAND-4: draw() must call _draw_classic (classic is default)"
        )
        # classic impl must contain █
        classic_src = inspect.getsource(nabd_logo._draw_classic)
        assert "█" in classic_src, "_draw_classic must still contain █"


    # ── ع4: prompt_wires_animated_indicator ─────────────────────────────────

    def test_prompt_wires_animated_indicator(self):
        """BRAND-4: toolbar wiring removed; indicator functions survive in cc_style.

        BRAND-2 wired typing_indicator into main.py bottom_toolbar.
        BRAND-4 removes that wiring — but the functions must remain in cc_style
        as available (unwired) primitives.
        """
        import ui.cc_style as cc_style
        assert hasattr(cc_style, "typing_indicator_frame"), (
            "typing_indicator_frame must remain in cc_style (unwired)"
        )
        assert hasattr(cc_style, "typing_indicator_frames"), (
            "typing_indicator_frames must remain in cc_style (unwired)"
        )
        # main.py must NOT wire the indicator anymore
        src = inspect.getsource(main)
        assert "typing_indicator" not in src, (
            "BRAND-4: main.py must NOT call typing_indicator (wiring removed)"
        )
