"""bg_gray was buried after a census, not after a grep.

Human ruling (Am, 2026-08-06 12:45 - "1A").

Reasoning (assistant, accepted by that ruling): engine/renderer.py holds
exactly one dynamic read of _COLORS - badge_line's _COLORS.get(color, ...) -
and all eight callers pass a literal: cyan x3, yellow x3, green, red, plus
the "cyan" default. _COLORS is not exported anywhere. No runtime string can
reach "bg_gray", so the key had zero reachable readers.
"""

import pathlib

from engine.renderer import _COLORS

_SRC = pathlib.Path(__file__).resolve().parents[1] / "engine" / "renderer.py"


def test_bg_gray_key_is_absent():
    assert "bg_gray" not in _COLORS, (
        "_COLORS still carries 'bg_gray'; it was deleted under ruling 1A "
        "because no caller of badge_line can ever name it"
    )


def test_bg_gray_escape_is_absent():
    src = _SRC.read_text(encoding="utf-8")
    assert "48;5;236" not in src, (
        "the bg_gray escape 48;5;236 returned to engine/renderer.py"
    )
