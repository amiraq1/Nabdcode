"""Tests for Phase 3 keyboard navigation keybindings.

Covers:
  - navigation disabled ignores keys
  - first navigation selects first widget
  - next() (down arrow, j)
  - previous() (up arrow, k)
  - wrap around
  - Enter toggles widget
  - Space toggles widget
  - Esc exits navigation mode
  - redraw called exactly once per action
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ui.widgets.tool_result import ToolResultWidget
from ui.widgets.tool_result_list import ToolResultList
from ui.keybindings import create_navigation_keybindings
from ui.theme import CUSTOM_THEME
from tests.support.render import make_console, render_to_text


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_list() -> ToolResultList:
    """Create a ToolResultList with a silent, dimension-pinned console."""
    console = make_console(width=120, height=25, theme=CUSTOM_THEME)
    return ToolResultList(console=console)


def _make_widget(name: str = "read", output: str = "short") -> ToolResultWidget:
    return ToolResultWidget(name, output)


def _make_widget(name: str = "read", output: str = "short") -> ToolResultWidget:
    return ToolResultWidget(name, output)


# prompt_toolkit normalises some keys:
#   "enter"   -> Keys.ControlM  (value "c-m")
#   "c-space" -> Keys.ControlAt (value "c-@")
_KEY_ALIASES = {"enter": "c-m", "c-space": "c-@"}


def _get_handler(bindings, key):
    """Return the handler function registered for *key* in *bindings*."""
    target = _KEY_ALIASES.get(key, key)
    for binding in bindings.bindings:
        for k in binding.keys:
            if isinstance(k, str) and k == target:
                return binding.handler
            if hasattr(k, "value") and k.value == target:
                return binding.handler
    raise KeyError(f"No binding for key: {key}")


class _MockEvent:
    """Minimal stand-in for prompt_toolkit's KeyPressEvent."""


def _make_nav(tool_result_list, navigation_enabled=True):
    """Build keybindings with mutable state containers for testing.

    Returns ``(bindings, nav_enabled, external_redraw_calls)``.
    """
    nav_enabled = [navigation_enabled]
    external_redraw_calls = [0]

    def _is_enabled():
        return nav_enabled[0]

    def _set_enabled(v):
        nav_enabled[0] = v

    def _redraw():
        external_redraw_calls[0] += 1

    bindings = create_navigation_keybindings(
        tool_result_list=tool_result_list,
        redraw=_redraw,
        navigation_enabled=_is_enabled,
        set_navigation_enabled=_set_enabled,
    )
    return bindings, nav_enabled, external_redraw_calls


# ── Tests ────────────────────────────────────────────────────────────────────

def test_navigation_disabled_ignores_keys():
    """When navigation_enabled() is False, all keys are ignored."""
    lst = _make_list()
    lst.add(_make_widget("read", "a"))
    lst.add(_make_widget("read", "b"))
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=False)

    for key in ("j", "down", "k", "up", "enter", "c-space", "escape"):
        handler = _get_handler(bindings, key)
        handler(_MockEvent())

    assert lst.current_index == -1
    assert redraw_calls[0] == 0


def test_first_navigation_selects_first_widget():
    """First navigation key selects the first widget."""
    lst = _make_list()
    lst.add(_make_widget("read", "a"))
    lst.add(_make_widget("read", "b"))
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    handler = _get_handler(bindings, "j")
    handler(_MockEvent())

    assert lst.current_index == 0
    assert lst.current() is not None
    assert lst.current().selected is True


def test_next_down_arrow():
    """Down arrow moves selection forward."""
    lst = _make_list()
    w0 = _make_widget("read", "a")
    w1 = _make_widget("read", "b")
    lst.add(w0)
    lst.add(w1)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    handler = _get_handler(bindings, "down")
    handler(_MockEvent())  # select first
    handler(_MockEvent())  # move to second

    assert lst.current_index == 1
    assert w1.selected is True
    assert w0.selected is False


def test_next_j_key():
    """j key moves selection forward."""
    lst = _make_list()
    lst.add(_make_widget("read", "a"))
    lst.add(_make_widget("read", "b"))
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    handler = _get_handler(bindings, "j")
    handler(_MockEvent())

    assert lst.current_index == 0


def test_previous_up_arrow():
    """Up arrow wraps from unselected to last widget."""
    lst = _make_list()
    w0 = _make_widget("read", "a")
    w1 = _make_widget("read", "b")
    w2 = _make_widget("read", "c")
    lst.add(w0)
    lst.add(w1)
    lst.add(w2)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    handler = _get_handler(bindings, "up")
    handler(_MockEvent())

    assert lst.current_index == 2
    assert w2.selected is True


def test_previous_k_key():
    """k key wraps from unselected to last widget."""
    lst = _make_list()
    lst.add(_make_widget("read", "a"))
    lst.add(_make_widget("read", "b"))
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    handler = _get_handler(bindings, "k")
    handler(_MockEvent())

    assert lst.current_index == 1


def test_wrap_around_down():
    """Down arrow wraps from last back to first."""
    lst = _make_list()
    w0 = _make_widget("read", "a")
    w1 = _make_widget("read", "b")
    lst.add(w0)
    lst.add(w1)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    handler = _get_handler(bindings, "down")
    handler(_MockEvent())  # 0
    handler(_MockEvent())  # 1
    handler(_MockEvent())  # wrap → 0

    assert lst.current_index == 0
    assert w0.selected is True
    assert w1.selected is False


def test_wrap_around_up():
    """Up arrow wraps from first back to last."""
    lst = _make_list()
    w0 = _make_widget("read", "a")
    w1 = _make_widget("read", "b")
    lst.add(w0)
    lst.add(w1)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    handler = _get_handler(bindings, "up")
    handler(_MockEvent())  # -1 → 1 (last)
    handler(_MockEvent())  # 1 → 0
    handler(_MockEvent())  # 0 → 1 (wrap)

    assert lst.current_index == 1
    assert w1.selected is True
    assert w0.selected is False


def test_enter_toggles_widget():
    """Enter toggles the current widget's collapse state."""
    lst = _make_list()
    w = _make_widget("read", "line1\nline2\nline3\nline4\nline5\nline6")
    lst.add(w)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    # Select first
    handler = _get_handler(bindings, "j")
    handler(_MockEvent())

    assert w.is_collapsed is True

    # Toggle with Enter
    enter_handler = _get_handler(bindings, "enter")
    enter_handler(_MockEvent())

    assert w.is_collapsed is False  # toggled

    # Toggle back
    enter_handler(_MockEvent())
    assert w.is_collapsed is True  # toggled back


def test_space_toggles_widget():
    """Space (c-space) toggles the current widget's collapse state."""
    lst = _make_list()
    w = _make_widget("read", "line1\nline2\nline3\nline4\nline5\nline6")
    lst.add(w)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    # Select first
    handler = _get_handler(bindings, "j")
    handler(_MockEvent())

    assert w.is_collapsed is True

    # Toggle with Space
    space_handler = _get_handler(bindings, "c-space")
    space_handler(_MockEvent())

    assert w.is_collapsed is False  # toggled


def test_esc_exits_navigation_mode():
    """Esc exits navigation mode and deselects current widget."""
    lst = _make_list()
    w = _make_widget("read", "a")
    lst.add(w)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=True)

    # Select first
    handler = _get_handler(bindings, "j")
    handler(_MockEvent())
    assert lst.current_index == 0
    assert w.selected is True

    # Press Esc
    esc_handler = _get_handler(bindings, "escape")
    esc_handler(_MockEvent())

    assert nav_enabled[0] is False  # navigation disabled
    assert lst.current_index == -1  # deselected
    assert w.selected is False  # widget deselected
    assert redraw_calls[0] == 1  # external redraw called once


def test_esc_ignored_when_disabled():
    """Esc is ignored when navigation is already disabled."""
    lst = _make_list()
    w = _make_widget("read", "a")
    lst.add(w)
    bindings, nav_enabled, redraw_calls = _make_nav(lst, navigation_enabled=False)

    esc_handler = _get_handler(bindings, "escape")
    esc_handler(_MockEvent())

    assert nav_enabled[0] is False
    assert redraw_calls[0] == 0


def test_redraw_called_once_per_action():
    """Redraw is called exactly once per navigation action.

    next() / previous() / toggle_current() call ``tool_result_list.redraw()``
    internally (tracked via ``internal_calls``).  Esc calls the external
    ``redraw`` callback (tracked via ``external_calls``).
    """
    lst = _make_list()
    lst.add(_make_widget("read", "a"))
    lst.add(_make_widget("read", "b"))

    # Track internal redraw (tool_result_list.redraw)
    internal_calls = [0]
    def _mock_internal_redraw():
        internal_calls[0] += 1
    lst.redraw = _mock_internal_redraw

    # Track external redraw callback
    external_calls = [0]
    def _external_redraw():
        external_calls[0] += 1

    nav_enabled = [True]
    bindings = create_navigation_keybindings(
        tool_result_list=lst,
        redraw=_external_redraw,
        navigation_enabled=lambda: nav_enabled[0],
        set_navigation_enabled=lambda v: nav_enabled.__setitem__(0, v),
    )

    # next() → internal redraw once
    handler = _get_handler(bindings, "j")
    handler(_MockEvent())
    assert internal_calls[0] == 1
    assert external_calls[0] == 0

    # previous() → internal redraw once
    up_handler = _get_handler(bindings, "up")
    up_handler(_MockEvent())
    assert internal_calls[0] == 2
    assert external_calls[0] == 0

    # toggle → internal redraw once
    toggle_handler = _get_handler(bindings, "enter")
    toggle_handler(_MockEvent())
    assert internal_calls[0] == 3
    assert external_calls[0] == 0

    # esc → external redraw once (deselect_current does NOT call internal redraw)
    esc_handler = _get_handler(bindings, "escape")
    esc_handler(_MockEvent())
    assert internal_calls[0] == 3  # unchanged
    assert external_calls[0] == 1


if __name__ == "__main__":
    test_navigation_disabled_ignores_keys()
    test_first_navigation_selects_first_widget()
    test_next_down_arrow()
    test_next_j_key()
    test_previous_up_arrow()
    test_previous_k_key()
    test_wrap_around_down()
    test_wrap_around_up()
    test_enter_toggles_widget()
    test_space_toggles_widget()
    test_esc_exits_navigation_mode()
    test_esc_ignored_when_disabled()
    test_redraw_called_once_per_action()
    print("All keybinding tests passed.")
