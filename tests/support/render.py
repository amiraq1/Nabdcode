"""Canonical test/evidence render helper (Am+8 D-3b).

Rich honors ``width`` ONLY when ``height`` is also supplied; without both it
falls through to the real terminal dimensions (80x25 on Termux), so a
width-only Console "works" only by coincidence. Every test snapshot and every
docs/*.ansi evidence capture must go through this single helper so the
measurement is identical on Termux and in a headless CI.
"""
from __future__ import annotations

from rich.console import Console, RenderableType


def render_to_text(
    renderable: RenderableType,
    width: int = 80,
    height: int = 25,
    theme=None,
) -> str:
    """Render *renderable* to a string with BOTH dimensions pinned.

    force_terminal=True and color_system="truecolor" are mandatory so the
    emitted ANSI is identical on Termux and in headless CI.
    """
    import io

    buf = io.StringIO()
    console = Console(
        file=buf,
        width=width,
        height=height,
        force_terminal=True,
        color_system="truecolor",
        theme=theme,
    )
    console.print(renderable)
    return buf.getvalue()
