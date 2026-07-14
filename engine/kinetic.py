"""engine/kinetic.py — Kinetic State Engine & Atomic Spinner.

A minimalist, industrial TUI layer that maps agent-loop signals to elite
cyber-verbs and renders a single, zero-flicker live status line via
``rich.live.Live``.

Design
──────
* Subscribes to the existing ``engine.events.bus`` events. It does NOT invent
  new event names and does NOT mutate any execution architecture.
* A dedicated daemon spinner thread owns the ``Live`` context. It advances the
  Braille spinner frame every 100ms and calls ``live.update(refresh=True)`` so
  the screen actually redraws. Bus callbacks only mutate shared state
  (verb / token count / phase) under a lock — they never touch the terminal
  directly, so the main async REPL loop is never blocked and Termux never
  jitters.
* ``auto_refresh=False`` guarantees Rich spawns NO internal refresh thread; our
  single spinner thread is the only writer, so there is no lock contention and
  therefore no flicker or deadlock.
* On ``loop_finished`` / ``loop_error`` / ``loop_interrupted`` the live line is
  cleared (transient wipe) and put back into its idle-but-alive state so the
  engine survives across turns in the REPL. A hard ``stop()`` fully tears down
  the Live context + thread on REPL exit.

Verbs (kinetic vocabulary)
─────────────────────────
* LLM invocation        → Structuring / Architecting / Contemplating
* Tool / shell active   → Sculpting / Injecting / Patching / Choreographing
* Verification/critique → Auditing / Verifying / Recalibrating
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any

from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text

from engine.events import bus


# Braille spinner frames, advanced at 100ms.
_SPINNER_FRAMES: tuple[str, ...] = (
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"
)

# Kinetic vocabulary — randomly sampled per phase entry.
_LLM_VERBS: tuple[str, ...] = ("Structuring...", "Architecting...", "Contemplating...")
_TOOL_VERBS: tuple[str, ...] = ("Sculpting...", "Injecting...", "Patching...", "Choreographing...")
_VERIFY_VERBS: tuple[str, ...] = ("Auditing...", "Verifying...", "Recalibrating...")
# Phase5 (GoalSpec): objective-aware verbs shown while the Verifier evaluates
# the active GoalSpec's success criteria — distinct from generic verification.
_GOAL_VERBS: list[str] = [
    "Pursuing Objective...",
    "Anchoring Criteria...",
    "Proving Goal...",
    "Verifying Outcome...",
    "Goal Achieved ✓"
]

_SPIN_INTERVAL: float = 0.10  # 100 ms per frame

# Idle verb shown between phases / across turns.
_IDLE_VERB: str = "Examining..."


def _fmt_tokens(n: int) -> str:
    """Render a token count like '15.6k' for the live status line."""
    if n >= 1000:
        return f"{n / 1000.0:.1f}k"
    return str(n)


class KineticStateEngine:
    """Owns one live status line and maps loop signals to cyber-verbs.

    Lifecycle: ``start()`` spawns the spinner thread + Live context (idempotent);
    ``stop()`` tears it down permanently (REPL exit). The loop-terminal events
    (``loop_finished`` / ``loop_error`` / ``loop_interrupted``) call
    ``_end_turn()`` — a transient wipe that preserves the engine for the next
    prompt instead of killing the shared daemon thread. Subscribe to bus events
    via ``wire()`` (idempotent).
    """

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._lock = threading.Lock()
        self._verb: str = _IDLE_VERB
        self._tokens: int = 0
        self._frame_idx: int = 0
        self._phase: str = "idle"
        self._live: Live | None = None
        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._wired: bool = False

    # ── Public lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Spin up the Live context + spinner thread (idempotent)."""
        # Build the initial renderable BEFORE taking the lock. ``_render`` snaps
        # shared state and then calls ``_build`` — it must NOT run while the lock
        # is held, since a plain ``threading.Lock`` is not reentrant and the
        # spinner thread acquires the same lock every 100ms.
        initial = self._render()
        with self._lock:
            if self._running:
                return
            self._running = True
            # auto_refresh=False: Rich spawns NO internal thread. Our single
            # spinner thread (below) is the only writer, calling update(refresh=True).
            # This removes any lock contention between Live's thread and ours,
            # guaranteeing zero flicker and no deadlock.
            self._live = Live(
                initial,
                console=self._console,
                refresh_per_second=10,
                transient=True,
                auto_refresh=False,
            )
            self._live.__enter__()
            self._thread = threading.Thread(target=self._spin_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Tear down the Live context and join the spinner thread (REPL exit)."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            live = self._live
            self._live = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if live is not None:
            try:
                live.__exit__(None, None, None)
            except Exception:
                pass

    def wire(self) -> None:
        """Subscribe to the existing bus events (idempotent)."""
        if self._wired:
            return
        bus.subscribe("llm_request_started", self._on_llm_start)
        bus.subscribe("llm_request_completed", self._on_llm_done)
        bus.subscribe("tool_started", self._on_tool_start)
        bus.subscribe("tool_completed", self._on_tool_done)
        bus.subscribe("tool_failed", self._on_tool_done)
        bus.subscribe("verifier_critique", self._on_verify)
        bus.subscribe("llm_token", self._on_token)
        # Phase5 (GoalSpec): the Verifier is now evaluating the active objective.
        # Switch to objective-aware verbs so the operator sees the goal-specific
        # verification phase rather than a generic verify verb.
        bus.subscribe("goal_verify", self._on_goal_verify)
        bus.subscribe("goal_set", self._on_goal_set)
        # Loop-terminal events wipe the line but keep the engine alive across
        # turns. They do NOT call stop() (that would kill the shared daemon
        # thread and permanently freeze the spinner for the whole session).
        bus.subscribe("loop_finished", self._end_turn)
        bus.subscribe("loop_error", self._end_turn)
        bus.subscribe("loop_interrupted", self._end_turn)
        self._wired = True

    # ── Bus handlers (only mutate shared state; never write to terminal) ──

    def _on_llm_start(self, payload: Any) -> None:
        self._enter_phase("llm", random.choice(_LLM_VERBS))

    def _on_llm_done(self, payload: Any) -> None:
        # LLM done → if a tool call follows it shows tool verbs; otherwise idle.
        self._enter_phase("idle", _IDLE_VERB, reset_tokens=False)

    def _on_tool_start(self, payload: Any) -> None:
        self._enter_phase("tool", random.choice(_TOOL_VERBS))

    def _on_tool_done(self, payload: Any) -> None:
        self._enter_phase("idle", _IDLE_VERB, reset_tokens=False)

    def _on_verify(self, payload: Any) -> None:
        self._enter_phase("verify", random.choice(_VERIFY_VERBS))

    def _on_goal_verify(self, payload: Any = None, **kwargs: Any) -> None:
        """Phase5 (GoalSpec): objective-specific verification verb.

        Shows the operator that the Verifier is anchoring the goal's success
        criteria against live evidence — distinct from the generic verify verb.
        """
        criteria_met = False
        if isinstance(payload, dict):
            criteria_met = bool(payload.get("criteria_met", False))
        elif isinstance(payload, bool):
            criteria_met = payload
        if "criteria_met" in kwargs:
            criteria_met = bool(kwargs["criteria_met"])
        with self._lock:
            if criteria_met:
                self._verb = _GOAL_VERBS[4]  # "Goal Achieved ✓"
            else:
                self._verb = _GOAL_VERBS[3]  # "Verifying Outcome..."
            self._phase = "goal"

    def _on_goal_set(self, payload: Any = None, **kwargs: Any) -> None:
        """Show objective-aware verb when goal is set"""
        desc = ""
        if isinstance(payload, str):
            desc = payload
        elif isinstance(payload, dict):
            desc = payload.get("goal_desc", "") or payload.get("raw_prompt", "")
        if not desc and "goal_desc" in kwargs:
            desc = str(kwargs["goal_desc"])
        with self._lock:
            self._verb = f" {_GOAL_VERBS[0]}: {desc[:30]}..."
            self._phase = "goal"

    def _on_token(self, payload: Any) -> None:
        with self._lock:
            tok = (payload or {}).get("token", "")
            # ~4 chars/token heuristic; count only non-trivial chunks.
            if tok:
                self._tokens += max(1, len(str(tok)) // 4)

    def _end_turn(self, payload: Any) -> None:
        """Transient wipe of the live line, keeping the engine alive."""
        with self._lock:
            self._phase = "idle"
            self._verb = _IDLE_VERB
            self._tokens = 0
        # A clean transient wipe so the next turn starts fresh without leaving
        # a stale frame frozen on screen.

    # ── Phase / verb state ─────────────────────────────────────────────────

    def _enter_phase(self, phase: str, verb: str, *, reset_tokens: bool = True) -> None:
        with self._lock:
            self._phase = phase
            self._verb = verb
            if reset_tokens:
                self._tokens = 0

    # ── Spinner thread (single owner of the Live context) ─────────────────

    def _spin_loop(self) -> None:
        """Advance the frame and redraw the live line every 100ms.

        This thread is the ONLY writer to the Live context, so there is no
        contention with Rich's own machinery (auto_refresh is off). It never
        blocks on agent work and never writes raw terminal output elsewhere.

        The shared state is snapshotted under the lock, then the renderable is
        built and the Live context updated *outside* the lock — this avoids
        re-entering ``self._lock`` (a plain ``threading.Lock`` is not
        reentrant) which would deadlock the spinner thread.
        """
        while True:
            with self._lock:
                if not self._running:
                    return
                self._frame_idx = (self._frame_idx + 1) % len(_SPINNER_FRAMES)
                live = self._live
                frame = _SPINNER_FRAMES[self._frame_idx]
                verb = self._verb
                tokens = self._tokens
            if live is not None:
                try:
                    live.update(
                        self._build(frame, verb, tokens), refresh=True
                    )
                except Exception:
                    # Terminal resized / detached mid-flight — skip this frame.
                    pass
            time.sleep(_SPIN_INTERVAL)

    # ── Renderable ─────────────────────────────────────────────────────────

    def _render(self) -> RenderableType:
        """Build the initial live status line (used once at ``start()``)."""
        with self._lock:
            frame = _SPINNER_FRAMES[self._frame_idx]
            verb = self._verb
            tokens = self._tokens
        return self._build(frame, verb, tokens)

    def _build(self, frame: str, verb: str, tokens: int) -> Text:
        """Compose the single, low-profile live status line."""
        if self._phase == "goal":
            return Text.assemble(
                Text(frame + " ", style="bold cyan"),
                Text(f"{verb.strip()} ", style="bold magenta"),
                Text(f"· {_fmt_tokens(tokens)} tokens" if tokens > 0 else "", style="dim")
            )
        return Text.assemble(
            Text(frame + " ", style="bold cyan"),
            Text(f"{verb.strip()} ", style="bold white"),
            Text(f"· {_fmt_tokens(tokens)} tokens" if tokens > 0 else "", style="dim")
        )


# Singleton — wire once at boot for the whole OS.
kinetic_engine = KineticStateEngine()


def start_kinetic_engine() -> KineticStateEngine:
    """Convenience boot hook: wire to bus, start the live line, return engine."""
    kinetic_engine.wire()
    kinetic_engine.start()
    return kinetic_engine
