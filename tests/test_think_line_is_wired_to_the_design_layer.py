"""W-1 guard — think_line must be wired to the design layer (ui/design).

Contracts:
  1. The waiting line speaks the ruled Arabic verb (يفكّر), not the English word.
  2. The waiting line wears the semantic THINKING colour (SEMANTIC.thinking.rgb).
  3. The waiting line carries the state icon (Icon.THINKING glyph, …).
  4. The hand-rolled palette colour (196;181;253) and the word "Thinking"
     are gone from the line.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.ui_theme import think_line
from ui.design.icons import Icon
from ui.design.primitives.personality import style_of
from ui.design.state import UIState
from ui.design.theme.semantic import SEMANTIC

_STYLE = style_of(UIState.THINKING)


def test_waiting_line_speaks_the_ruled_verb():
    line = think_line(None)
    assert _STYLE.verb in line


def test_waiting_line_wears_the_semantic_colour():
    line = think_line(None)
    r, g, b = SEMANTIC.thinking.rgb
    assert f"{r};{g};{b}" in line


def test_waiting_line_carries_the_state_icon():
    line = think_line(None)
    assert Icon.glyph(Icon.THINKING) in line


def test_the_hand_rolled_palette_is_gone_from_the_line():
    line = think_line(None)
    assert "196;181;253" not in line
    assert "Thinking" not in line
