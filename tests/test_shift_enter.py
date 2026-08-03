"""D-4.1 guards: Shift+Enter must be a newline, never a submit.

Measured on the 4273b33 anchor with create_pipe_input: the XTerm CSI form
(ESC [ 27;2;13~ ) is mapped by prompt_toolkit onto ControlM and submits, and
the kitty form (ESC [ 13;2u ) leaks literal ``[13;2u`` text into the buffer.
Neither inserts a newline, so the conditional-keep branch of D-4.1 applies:
a binding in the merged set makes both insert a newline while a plain Enter
keeps submitting. All guards are built on create_pipe_input and fail on the
anchor (``create_shift_enter_keybindings`` does not exist there).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.key_binding import merge_key_bindings
from prompt_toolkit.keys import Keys

from ui.keybindings import (
    create_navigation_keybindings,
    create_shift_enter_keybindings,
)
from ui.repl_termux import _setup_repl_keybindings

_KITTY = chr(27) + "[13;2u"  # kitty keyboard protocol: Shift+Enter
_CSI = chr(27) + "[27;2;13~"  # XTerm modifyOtherKeys: Shift+Enter


class _FakeList:
    """Minimal ToolResultList stand-in for the navigation bindings."""

    def toggle_current(self):
        pass

    def next(self):
        pass

    def previous(self):
        pass

    def deselect_current(self):
        pass

    def redraw(self):
        pass


def _shift_enter_only(nav_enabled: bool):
    return create_shift_enter_keybindings(navigation_enabled=lambda: nav_enabled)


def _real_chain(nav_enabled: bool):
    """Replicate run_repl's merged chain: [bindings, _nav_bindings, shift]."""
    nav_enabled_box = [nav_enabled]
    nav = create_navigation_keybindings(
        tool_result_list=_FakeList(),
        redraw=lambda: None,
        navigation_enabled=lambda: nav_enabled_box[0],
        set_navigation_enabled=lambda v: nav_enabled_box.__setitem__(0, v),
    )
    return merge_key_bindings(
        [
            _setup_repl_keybindings(),
            nav,
            create_shift_enter_keybindings(lambda: nav_enabled_box[0]),
        ]
    )


def _prompt(feed: str, bindings) -> str:
    with create_pipe_input() as inp:
        inp.send_text(feed)
        session = PromptSession(input=inp, history=None, key_bindings=bindings)
        return session.prompt()


def test_kitty_shift_enter_inserts_newline_not_submit():
    """The kitty form must insert a newline; only a real Enter submits."""
    result = _prompt(f"hello{_KITTY}world\r", _shift_enter_only(False))
    assert result == "hello\nworld"


def test_csi_shift_enter_inserts_newline_not_submit():
    """The XTerm form must insert a newline; only a real Enter submits."""
    result = _prompt(f"hello{_CSI}world\r", _shift_enter_only(False))
    assert result == "hello\nworld"


def test_both_encodings_mix_into_one_multiline_input():
    """Both encodings in one line accumulate into a single multi-line input."""
    result = _prompt(f"a{_KITTY}b{_CSI}c\r", _shift_enter_only(False))
    assert result == "a\nb\nc"


def test_plain_enter_still_submits():
    """A plain Enter keeps its submit behaviour (regression guard)."""
    result = _prompt("hello\r", _shift_enter_only(False))
    assert result == "hello"


def test_shift_enter_yields_while_navigation_active():
    """In navigation mode the shift-enter bindings stand down (nav owns Enter)."""
    active = create_shift_enter_keybindings(navigation_enabled=lambda: True)
    idle = create_shift_enter_keybindings(navigation_enabled=lambda: False)
    assert [b.keys for b in active.bindings] == [b.keys for b in idle.bindings]
    for binding in active.bindings:
        assert binding.filter() is False
    for binding in idle.bindings:
        assert binding.filter() is True
    # The CSI dispatch binding must sit on ControlM.
    assert any(b.keys == (Keys.ControlM,) for b in idle.bindings)


def test_real_chain_plain_enter_submits():
    """Through the REPL's real merged chain, a plain Enter still submits."""
    result = _prompt("hello\r", _real_chain(False))
    assert result == "hello"


def test_real_chain_kitty_shift_enter_is_newline():
    """Through the REPL's real merged chain, Shift+Enter is a newline."""
    result = _prompt(f"hello{_KITTY}world\r", _real_chain(False))
    assert result == "hello\nworld"
