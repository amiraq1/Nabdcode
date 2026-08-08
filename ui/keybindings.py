"""Keyboard navigation bindings for ToolResultList (Phase 3).

Enables arrow-key / vim-style navigation over tool results *after* the
agent finishes execution (``show_final_answer``).  During agent execution
all navigation keys are ignored — the prompt remains blocked and no widget
state changes occur.

Supported keys
--------------
Down Arrow / j  →  tool_result_list.next()
Up Arrow   / k  →  tool_result_list.previous()
Enter / Space   →  tool_result_list.toggle_current()
Esc             →  exit navigation mode, deselect current widget,
                   navigation disabled

All other keys are ignored while ``navigation_enabled()`` is ``False``.

D-4.1 also provides :func:`create_shift_enter_keybindings`: both Shift+Enter
encodings become a newline instead of a submit, standing down whenever
navigation is active.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

if TYPE_CHECKING:
    from ui.widgets.tool_result_list import ToolResultList


def create_navigation_keybindings(
    tool_result_list: "ToolResultList",
    redraw: Callable[[], None],
    navigation_enabled: Callable[[], bool],
    set_navigation_enabled: Callable[[bool], None],
    on_exit: Callable[[], None] | None = None,
) -> KeyBindings:
    """Create prompt_toolkit keybindings for navigating ``tool_result_list``.

    Parameters
    ----------
    tool_result_list
        The list container whose widgets will be navigated.
    redraw
        Callback that re-renders the widget list (used by the Esc handler
        after deselecting the current widget).
    navigation_enabled
        Zero-arg callable returning ``True`` when navigation is active
        (i.e. after ``show_final_answer``).
    set_navigation_enabled
        Setter used by the Esc handler to disable navigation.
    on_exit
        Optional callback invoked after Esc exits navigation mode (e.g.
        to hide the footer help bar).
    """
    bindings = KeyBindings()

    def _guard() -> bool:
        """Return ``True`` when navigation is active, ``False`` to ignore key."""
        return navigation_enabled()

    @bindings.add("down")
    @bindings.add("j")
    def _on_down(event) -> None:
        if not _guard():
            return
        tool_result_list.next()

    @bindings.add("up")
    @bindings.add("k")
    def _on_up(event) -> None:
        if not _guard():
            return
        tool_result_list.previous()

    @bindings.add("enter")
    @bindings.add("c-space")
    def _on_toggle(event) -> None:
        if not _guard():
            return
        tool_result_list.toggle_current()

    @bindings.add("escape")
    def _on_escape(event) -> None:
        if not _guard():
            return
        tool_result_list.deselect_current()
        redraw()
        set_navigation_enabled(False)
        if on_exit is not None:
            on_exit()

    return bindings


# XTerm modifyOtherKeys: Shift+Enter (the one encoding prompt_toolkit maps).
_CSI_SHIFT_ENTER = chr(27) + "[27;2;13~"


def create_shift_enter_keybindings(
    navigation_enabled: Callable[[], bool],
) -> KeyBindings:
    """Turn both Shift+Enter encodings into a newline instead of a submit.

    prompt_toolkit maps the XTerm modifyOtherKeys form (ESC [ 27;2;13~ ) onto
    ``Keys.ControlM``, so it submits; the kitty-protocol form (ESC [ 13;2u )
    is unmapped and leaks literal text into the buffer. Neither inserts a
    newline, so both are re-bound here.

    The kitty form is matched as its raw key sequence; the XTerm form arrives
    as a ControlM key press whose data still carries the original sequence, so
    the handler dispatches on ``key_sequence[-1].data`` and lets a plain Enter
    keep its submit behaviour.

    While ``navigation_enabled()`` is true the bindings stand down, so the
    navigation layer keeps ownership of Enter/Space/Escape.
    """
    not_navigating = Condition(lambda: not navigation_enabled())

    bindings = KeyBindings()

    @bindings.add("escape", "[", "1", "3", ";", "2", "u", filter=not_navigating)
    def _kitty_shift_enter(event) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add(Keys.ControlM, filter=not_navigating, eager=True)
    def _enter_or_csi_shift_enter(event) -> None:
        if event.key_sequence[-1].data == _CSI_SHIFT_ENTER:
            event.current_buffer.insert_text("\n")
        else:
            event.current_buffer.validate_and_handle()

    return bindings
