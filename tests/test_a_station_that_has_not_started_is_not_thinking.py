"""R-4.5B · الحارس الثامن — المحطة التي لم تبدأ لا تنطق "يفكّر".

يثبت ثلاثة عقود فقط:
  Contract 1 (semantics):  idle.verb != thinking.verb
  Contract 2 (visual face): idle and thinking carry distinct (color, icon)
  Contract 3 (live bar):   the fresh, never-started status bar render contains
                           no thinking verb at all.

No assumptions about weight / rhythm / spinner / layout / exact color
values or face count are asserted here -- only the three contracts below,
each grounded in the production renderer output captured in RECON_ONLY.
"""
from __future__ import annotations

from tests.support.render import render_to_text, strip_ansi
from ui.design.state import UIState
from ui.design.primitives.personality import style_of
from ui.widgets.status_bar import AgentStatusBar

THINKING_VERB = style_of(UIState.THINKING).verb


# ── Contract 1: semantics ──────────────────────────────────────────────
def test_idle_verb_differs_from_thinking_verb():
    """Contract 1: idle.verb != thinking.verb.

    A station that has not started (UIState.IDLE) must not borrow the
    THINKING personality's verb; otherwise an idle face will always read
    "يفكّر" even when no agent work is actually happening.
    """
    idle_verb = style_of(UIState.IDLE).verb
    assert idle_verb != THINKING_VERB, (
        "R-4.5B CONTRACT FAILED (idle verb): idle.verb == thinking.verb == "
        f"{idle_verb!r}; the idle face still wears the THINKING verb."
    )


# ── Contract 2: visual face ────────────────────────────────────────────
def test_idle_face_is_visually_distinct_from_thinking():
    """Contract 2: (idle.color, idle.icon) != (thinking.color, thinking.icon).

    Distinctness across the two personalities is enforced at the
    (color, icon) pair level; weight/rhythm/spinner are out of scope.
    """
    idle_style = style_of(UIState.IDLE)
    thinking_style = style_of(UIState.THINKING)
    assert (idle_style.color, idle_style.icon) != (
        thinking_style.color,
        thinking_style.icon,
    ), (
        "R-4.5B CONTRACT FAILED (idle face): idle and thinking share the "
        f"same (color, icon) -> ({idle_style.color!r}, {idle_style.icon!r})."
    )


# ── Contract 3: live bar ───────────────────────────────────────────────
def test_fresh_bar_does_not_speak_the_thinking_verb():
    """Contract 3: a never-started bar must not emit the thinking verb.

    AgentStatusBar() constructed with no active phase / no start() call must
    render a row whose faces reflect idle/pending state WITHOUT leaking the
    THINKING verb text.
    """
    bar = AgentStatusBar()
    text = strip_ansi(render_to_text(bar._build_renderable(), width=60))
    assert THINKING_VERB not in text, (
        "R-4.5B CONTRACT FAILED (fresh bar verb): the never-started bar "
        f"still renders the thinking verb {THINKING_VERB!r}. Render: {text!r}"
    )
