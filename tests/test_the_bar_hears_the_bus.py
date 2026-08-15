"""R-4.1 — Behavioral Red Guard: "The Bar That Actually Hears the Bus".

This test does NOT inspect source. It proves the live chain by execution:

    REAL EVENT
        → REAL EVENT BUS
        → REAL wire_events(ctx)        (main.wire_events — the real wiring path)
        → REAL EVENT DELIVERY
        → REAL EVENT HANDLER
        → REAL AgentStatusBar
        → OBSERVABLE STATE CHANGE

Everything is measured, never guessed:
  - EventBus:   bus.subscribe(event_name, callback) -> Callable
                bus.emit(event_name, payload=None)
                bus._subscribers: Dict[str, Dict[str, Callable]]
  - wire_events(ctx) touches only ctx.renderer, ctx.metrics, ctx.todo_manager
    and calls status_bar.start()/stop() on llm_request_started / llm_request_completed.
  - AgentStatusBar: PHASES = ["Thinking", "Running Tools", "Generating"];
    _phase_states: dict[str, str]; set_active(phase); set_complete();
    wire() subscribes to llm_request_started, tool_started, loop_completed,
    show_final_answer.
  - make_console(width, height) comes from tests/support/render.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main as main_mod
from core.kernel.events import bus
from tests.support.render import make_console
from ui.widgets.status_bar import AgentStatusBar

_LLM_STARTED = "llm_request_started"
_TOOL_STARTED = "tool_started"
_FINAL_ANSWER = "show_final_answer"


def _make_ctx(monkeypatch):
    """Real AppContext, real Renderer, pinned AgentStatusBar via monkeypatch.

    Status-bar isolation (§9): replace main.status_bar with a fresh
    AgentStatusBar(console=make_console(width=80, height=25)).
    """
    from core.app_context import AppContext

    ctx = AppContext.build()

    monkeypatch.setattr(
        main_mod,
        "status_bar",
        AgentStatusBar(console=make_console(width=80, height=25)),
    )
    return ctx


def _snapshot_subscribers() -> dict:
    """Identity snapshot of the global bus subscriber registry (no deep copy).

    Copy subscribers by reference (identity), not by value. The registry may
    hold live subscribers whose bound self carries unpicklable state (e.g. an
    RLock inside a MetricsEngine). Deep-copying them raises TypeError under
    pytest-randomly ordering; copying identity avoids that entirely while still
    letting restore put the registry back on the SAME dict object.
    """
    return {event: dict(subscribers) for event, subscribers in bus._subscribers.items()}


def _restore_subscribers(snapshot: dict) -> None:
    """Restore onto the SAME dict object in-place — no identity change."""
    bus._subscribers.clear()
    bus._subscribers.update(snapshot)


def _emit_and_check(
    ctx,
    monkeypatch,
    event_name: str,
    payload: dict,
    phase_under_test: str,
    expected_state: str,
    contract_label: str,
) -> None:
    """Shared behavior: wire via the real path, emit the real event, observe state."""
    subscribers_before = _snapshot_subscribers()
    try:
        main_mod.wire_events(ctx)

        bus.emit(event_name, payload)

        bar = main_mod.status_bar
        observed = bar._phase_states.get(phase_under_test)

        assert observed == expected_state, (
            "R-4.1 CONTRACT FAILED: "
            f"{contract_label} — expected phase {phase_under_test!r} to be "
            f"{expected_state!r} after real bus.emit({event_name!r}, {payload!r}) "
            f"through real main.wire_events(ctx), but observed {observed!r}. "
            "The AgentStatusBar is not hearing the bus on the live wiring path."
        )
    finally:
        _restore_subscribers(subscribers_before)


def test_the_bar_hears_llm_request_started(monkeypatch):
    """Contract 1: llm_request_started must drive the real bar to active Thinking."""
    ctx = _make_ctx(monkeypatch)
    _emit_and_check(
        ctx,
        monkeypatch,
        _LLM_STARTED,
        {"step": 1},
        "Thinking",
        "active",
        "llm_request_started -> Thinking active",
    )


def test_the_bar_hears_tool_started(monkeypatch):
    """Contract 2: tool_started must drive the real bar to active Running Tools."""
    ctx = _make_ctx(monkeypatch)
    _emit_and_check(
        ctx,
        monkeypatch,
        _TOOL_STARTED,
        {"tool": "execute_shell", "args": {"command": "echo hi"}},
        "Running Tools",
        "active",
        "tool_started -> Running Tools active",
    )


def test_the_bar_hears_show_final_answer(monkeypatch):
    """Contract 3: show_final_answer must drive the real bar to complete.

    Stage 2: a *direct* answer (no tool_started) must complete Thinking
    and Generating but leave Running Tools as ``pending``.
    """
    ctx = _make_ctx(monkeypatch)

    subscribers_before = _snapshot_subscribers()
    try:
        main_mod.wire_events(ctx)

        bar = main_mod.status_bar
        # Simulate the real event sequence for a direct answer:
        # llm_request_started → loop_completed → show_final_answer
        bus.emit("llm_request_started", {"step": 1})
        bus.emit("loop_completed", {"reason": "completed", "output": "Hello!"})
        bus.emit("show_final_answer", {"final_answer": "Hello!"})

        assert bar._phase_states["Thinking"] == "done"
        assert bar._phase_states["Running Tools"] == "pending"  # no tool started
        assert bar._phase_states["Generating"] == "done"
    finally:
        _restore_subscribers(subscribers_before)


def test_the_bar_marks_tools_done_after_tool_started(monkeypatch):
    """When a tool IS started, show_final_answer must mark Tools as done."""
    ctx = _make_ctx(monkeypatch)

    subscribers_before = _snapshot_subscribers()
    try:
        main_mod.wire_events(ctx)

        bar = main_mod.status_bar
        bus.emit("llm_request_started", {"step": 1})
        bus.emit("tool_started", {"tool": "execute_shell", "args": {"command": "echo hi"}})
        bus.emit("loop_completed", {"reason": "completed", "output": "done"})
        bus.emit("show_final_answer", {"final_answer": "done"})

        assert bar._phase_states["Thinking"] == "done"
        assert bar._phase_states["Running Tools"] == "done"
        assert bar._phase_states["Generating"] == "done"
    finally:
        _restore_subscribers(subscribers_before)
