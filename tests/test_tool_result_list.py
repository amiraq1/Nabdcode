"""Tests for the ToolResultList container (Phase 2: Selection Model)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ui.widgets.tool_result import ToolResultWidget
from ui.widgets.tool_result_list import ToolResultList
from ui.theme import CUSTOM_THEME
from tests.support.render import make_console


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_list() -> ToolResultList:
    """Create a ToolResultList with a silent, dimension-pinned console."""
    console = make_console(width=120, height=25, theme=CUSTOM_THEME)
    return ToolResultList(console=console)


def _make_widget(name: str = "read", output: str = "short") -> ToolResultWidget:
    return ToolResultWidget(name, output)


# ── add() ────────────────────────────────────────────────────────────────────

def test_add_increases_len():
    lst = _make_list()
    assert len(lst) == 0
    lst.add(_make_widget())
    assert len(lst) == 1
    lst.add(_make_widget())
    assert len(lst) == 2


def test_add_does_not_auto_select():
    """add() must NOT auto-select the widget."""
    lst = _make_list()
    w = _make_widget()
    lst.add(w)
    assert w.selected is False
    assert lst.current_index == -1


# ── next() ───────────────────────────────────────────────────────────────────

def test_next_selects_first_widget():
    """next() on an unselected list selects the first widget."""
    lst = _make_list()
    lst.add(_make_widget("read", "a"))
    lst.add(_make_widget("read", "b"))
    lst.add(_make_widget("read", "c"))

    lst.next()
    assert lst.current_index == 0
    assert lst.current() is not None
    assert lst.current().selected is True


def test_next_wraps_at_end():
    """next() wraps from last back to first."""
    lst = _make_list()
    w0 = _make_widget("read", "a")
    w1 = _make_widget("read", "b")
    w2 = _make_widget("read", "c")
    lst.add(w0)
    lst.add(w1)
    lst.add(w2)

    lst.next()  # 0
    assert lst.current_index == 0
    assert w0.selected is True
    lst.next()  # 1
    assert lst.current_index == 1
    assert w1.selected is True
    lst.next()  # 2
    assert lst.current_index == 2
    assert w2.selected is True
    lst.next()  # wrap → 0
    assert lst.current_index == 0
    assert w0.selected is True
    assert w2.selected is False  # previous deselected


def test_next_empty_noop():
    """next() on empty list is a no-op."""
    lst = _make_list()
    lst.next()
    assert lst.current_index == -1
    assert lst.current() is None


# ── previous() ───────────────────────────────────────────────────────────────

def test_previous_wraps_at_start():
    """previous() wraps from first back to last."""
    lst = _make_list()
    w0 = _make_widget("read", "a")
    w1 = _make_widget("read", "b")
    w2 = _make_widget("read", "c")
    lst.add(w0)
    lst.add(w1)
    lst.add(w2)

    lst.previous()  # -1 → 2 (last)
    assert lst.current_index == 2
    assert w2.selected is True
    lst.previous()  # 2 → 1
    assert lst.current_index == 1
    assert w1.selected is True
    lst.previous()  # 1 → 0
    assert lst.current_index == 0
    assert w0.selected is True
    lst.previous()  # wrap → 2
    assert lst.current_index == 2
    assert w2.selected is True
    assert w0.selected is False  # previous deselected


def test_previous_empty_noop():
    """previous() on empty list is a no-op."""
    lst = _make_list()
    lst.previous()
    assert lst.current_index == -1
    assert lst.current() is None


# ── toggle_current() ─────────────────────────────────────────────────────────

def test_toggle_current_calls_widget_toggle():
    """toggle_current() must call toggle() on the current widget."""
    lst = _make_list()
    w = _make_widget("read", "line1\nline2\nline3\nline4\nline5\nline6")
    lst.add(w)
    lst.next()  # select w

    assert w.is_collapsed is True
    lst.toggle_current()
    assert w.is_collapsed is False  # toggled
    lst.toggle_current()
    assert w.is_collapsed is True  # toggled back


def test_toggle_current_empty_noop():
    """toggle_current() on empty list is a no-op."""
    lst = _make_list()
    lst.toggle_current()  # must not raise


# ── clear() ──────────────────────────────────────────────────────────────────

def test_clear_resets_index():
    """clear() must reset _current_index to -1."""
    lst = _make_list()
    lst.add(_make_widget())
    lst.next()
    assert lst.current_index == 0
    lst.clear()
    assert lst.current_index == -1
    assert len(lst) == 0


def test_clear_calls_deselect_on_all():
    """clear() must call deselect() on every widget."""
    lst = _make_list()
    w0 = _make_widget("read", "a")
    w1 = _make_widget("read", "b")
    w2 = _make_widget("read", "c")
    lst.add(w0)
    lst.add(w1)
    lst.add(w2)
    lst.next()  # select w0
    lst.next()  # select w1

    assert w0.selected is False  # deselected by next()
    assert w1.selected is True

    lst.clear()
    assert w0.selected is False
    assert w1.selected is False
    assert w2.selected is False


# ── current() ────────────────────────────────────────────────────────────────

def test_current_returns_none_when_empty():
    """current() must return None when the list is empty."""
    lst = _make_list()
    assert lst.current() is None


def test_current_returns_widget():
    """current() must return the selected widget."""
    lst = _make_list()
    w = _make_widget("read", "a")
    lst.add(w)
    lst.next()
    assert lst.current() is w


# ── Extra: single widget ─────────────────────────────────────────────────────

def test_single_widget_next_next_same():
    """Single widget: add → next → next → current() is same widget."""
    lst = _make_list()
    w = _make_widget("read", "a")
    lst.add(w)
    lst.next()
    assert lst.current() is w
    lst.next()  # wraps to same widget
    assert lst.current() is w
    assert lst.current_index == 0


# ── Extra: after clear ───────────────────────────────────────────────────────

def test_after_clear_next_no_exception():
    """After clear(), next() must not raise and current() is None."""
    lst = _make_list()
    lst.add(_make_widget())
    lst.add(_make_widget())
    lst.next()
    lst.clear()
    lst.next()  # no exception
    assert lst.current() is None
    assert lst.current_index == -1


# ── redraw() ─────────────────────────────────────────────────────────────────

def test_redraw_prints_all_widgets():
    """redraw() must compose every widget's render() through the Column
    atom (D-3c.2: the list renders via atoms, not a manual print loop)."""
    console = make_console(width=120, height=25, theme=CUSTOM_THEME)
    lst = ToolResultList(console=console)
    lst.add(_make_widget("read", "first"))
    lst.add(_make_widget("read", "second"))

    lst.redraw(console)
    output = console.file.getvalue()
    assert "first" in output
    assert "second" in output


if __name__ == "__main__":
    test_add_increases_len()
    test_add_does_not_auto_select()
    test_next_selects_first_widget()
    test_next_wraps_at_end()
    test_next_empty_noop()
    test_previous_wraps_at_start()
    test_previous_empty_noop()
    test_toggle_current_calls_widget_toggle()
    test_toggle_current_empty_noop()
    test_clear_resets_index()
    test_clear_calls_deselect_on_all()
    test_current_returns_none_when_empty()
    test_current_returns_widget()
    test_single_widget_next_next_same()
    test_after_clear_next_no_exception()
    test_redraw_prints_all_widgets()
    print("All ToolResultList tests passed.")
