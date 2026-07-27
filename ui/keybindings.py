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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from prompt_toolkit.key_binding import KeyBindings

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
