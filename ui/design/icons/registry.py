"""Centralized icon registry.

Every glyph used by the UI lives here. Widgets must never hardcode Unicode
icons; they resolve them through ``Icon``. Each member has a DISTINCT glyph so
no member is silently folded into an alias — aliased members are dropped by
``list(Icon)``, which previously hid DELETE/RESUME/CHECK/STREAMING/WAITING
from the registry.
"""
from __future__ import annotations

from enum import Enum


class Icon(Enum):
    """UI icons. Value is the display glyph (resolved lazily at render time)."""

    # status / lifecycle
    SUCCESS = "\u2713"      # check mark
    CHECK = "\u2714"        # heavy check mark
    WARNING = "\u26a0"      # warning sign
    ERROR = "\u2716"        # heavy multiplication x
    DELETE = "\u2717"       # ballot x
    THINKING = "\u2026"     # ellipsis
    STREAMING = "\u21bb"    # clockwise open-circle arrow
    WAITING = "\u23f3"      # hourglass
    RUNNING = "\u25b6"      # black right-pointing triangle
    RESUME = "\u25b8"       # right-pointing small triangle
    IDLE = "\u25cb"         # white circle
    COLLAPSE = "\u25ba"     # black right-pointing pointer (collapsed header)
    SELECT = "\u276f"       # heavy right-pointing angle quote (selection cursor)
    PLANNING = "\u22c5"     # dot operator
    PAUSE = "\u23f8"        # double vertical bar
    STOP = "\u23f9"         # double vertical bar
    CANCEL = "\u2715"       # multiplication x
    LOADING = "\u21bb"      # loading spinner glyph (distinct member)
    DISABLED = "\u2298"     # prohibited / disabled (circled slash)

    # entities / actions
    FOLDER = "\U0001f4c1"
    FILE = "\U0001f4c4"
    GIT = "\u2387"          # branch / hex glyph
    DIFF = "\u00b1"
    MEMORY = "\U0001f4be"
    SEARCH = "\U0001f50d"
    EDIT = "\u270e"
    COPY = "\u2399"
    INFO = "\u2139"

    @classmethod
    def glyph(cls, member) -> str:
        """Resolve an Icon (instance or name) to its glyph."""
        if isinstance(member, cls):
            return member.value
        if isinstance(member, str):
            return cls[member].value
        raise ValueError(f"Unknown icon: {member!r}")
