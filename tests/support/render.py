"""Canonical test/evidence render helper (Am+8 D-3b).

Rich honors ``width`` ONLY when ``height`` is also supplied; without both it
falls through to the real terminal dimensions (80x25 on Termux), so a
width-only Console "works" only by coincidence. Every test snapshot and every
docs/*.ansi evidence capture must go through this single helper so the
measurement is identical on Termux and in a headless CI.
"""
from __future__ import annotations

import io
import re

from rich.console import Console, RenderableType

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from *text*.

    Single owner for ANSI stripping in the test tree.
    """
    return _ANSI.sub("", text)


def make_console(
    width: int = 80,
    height: int = 25,
    theme=None,
) -> Console:
    """Return a Console with BOTH dimensions pinned to a StringIO buffer.

    ``height`` is mandatory: Rich honors ``width`` only when height is
    supplied.
    """
    buf = io.StringIO()
    return Console(
        file=buf,
        width=width,
        height=height,
        force_terminal=True,
        force_interactive=True,
        color_system="truecolor",
        theme=theme,
    )


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
