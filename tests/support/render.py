"""Canonical test/evidence render helper (Am+8 D-3b).

Rich honors ``width`` ONLY when ``height`` is also supplied; without both it
falls through to the real terminal dimensions (80x25 on Termux), so a
width-only Console "works" only by coincidence. Every test snapshot and every
docs/*.ansi evidence capture must go through this single helper so the
measurement is identical on Termux and in a headless CI.
"""
from __future__ import annotations

import io

from rich.console import Console, RenderableType


def make_console(
    width: int = 80,
    height: int = 25,
    theme=None,
    color_system: str | None = "truecolor",
) -> Console:
    """Return a Console with BOTH dimensions pinned to a StringIO buffer.

    ``height`` is mandatory: Rich honors ``width`` only when height is
    supplied.  ``color_system`` defaults to ``"truecolor"`` (match
    :func:`render_to_text`); pass ``None`` for a non-color sink.
    """
    buf = io.StringIO()
    return Console(
        file=buf,
        width=width,
        height=height,
        force_terminal=True,
        color_system=color_system,
        theme=theme,
    )


def render_to_text(
    renderable: RenderableType,
    width: int = 80,
    height: int = 25,
    theme=None,
    color_system: str | None = "truecolor",
) -> str:
    """Render *renderable* to a string with BOTH dimensions pinned.

    force_terminal=True and color_system="truecolor" are mandatory so the
    emitted ANSI is identical on Termux and in headless CI.
    Pass ``color_system=None`` for a plain-text sink (no ANSI codes).
    """
    buf = io.StringIO()
    console = Console(
        file=buf,
        width=width,
        height=height,
        force_terminal=True,
        color_system=color_system,
        theme=theme,
    )
    console.print(renderable)
    return buf.getvalue()
