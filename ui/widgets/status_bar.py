"""AgentStatusBar — phase-aware status bar.

Renders a single Rich Live line showing three pipeline phases
(Thinking → Running Tools → Generating) with per-phase state indicators.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text

from core.kernel.events import bus
from ui.design.primitives import Row, StatusLine, SectionPanel
from ui.design.state import UIState
from ui.design.theme.semantic import SEMANTIC


class AgentStatusBar:
    """Phase-aware status bar for the NABD agent pipeline.

    Phases: Thinking → Running Tools → Generating
    """

    PHASES = ["Thinking", "Running Tools", "Generating"]

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()
        self._phase_states: dict[str, str] = {p: "pending" for p in self.PHASES}
        self._step: int | None = None
        self._live: Live | None = None
        self._running: bool = False
        self._wired: bool = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the Live display (idempotent)."""
        if self._running:
            return
        self._running = True
        
        initial = self._build_renderable()
        self._live = Live(
            initial,
            console=self._console,
            transient=True,
            auto_refresh=False,
        )
        self._live.__enter__()

    def stop(self) -> None:
        """Tear down the Live context."""
        if not self._running:
            return
        self._running = False
        live = self._live
        self._live = None
        
        if live is not None:
            try:
                live.__exit__(None, None, None)
            except Exception:
                pass

    def wire(self) -> None:
        """Subscribe to EventBus events (idempotent)."""
        if self._wired:
            return
        bus.subscribe("llm_request_started", self._on_llm_start)
        bus.subscribe("tool_started", self._on_tool_start)
        bus.subscribe("loop_completed", self._on_loop_completed)
        bus.subscribe("show_final_answer", self._on_final_answer)
        self._wired = True

    # ── Event handlers ─────────────────────────────────────────────────

    def _on_llm_start(self, payload: Any) -> None:
        if isinstance(payload, dict) and "step" in payload:
            self.set_step(payload.get("step"))
        self.set_active("Thinking")

    def _on_tool_start(self, payload: Any) -> None:
        if isinstance(payload, dict) and "step" in payload:
            self.set_step(payload.get("step"))
        self.set_active("Running Tools")

    def _on_loop_completed(self, payload: Any) -> None:
        self.set_active("Generating")

    def _on_final_answer(self, payload: Any) -> None:
        self.set_complete()

    # ── Public API ─────────────────────────────────────────────────────

    def set_active(self, phase: str) -> None:
        """Activate *phase*; mark all earlier phases done."""
        if phase not in self._phase_states:
            return
        idx = self.PHASES.index(phase)
        for i, p in enumerate(self.PHASES):
            if i < idx:
                self._phase_states[p] = "done"
            elif i == idx:
                self._phase_states[p] = "active"
            else:
                self._phase_states[p] = "pending"
        self._update_live()

    def set_complete(self) -> None:
        """Mark all phases done, stop Live, print stats line."""
        for p in self.PHASES:
            self._phase_states[p] = "done"
        self._update_live()
        self.stop()
        # V-07b: No fabricated affordances. Removed fake timer and token/file counts
        # from the completion stats since they were not accurately maintained.

    def set_step(self, step: Any) -> None:
        if step is not None:
            try:
                self._step = int(step)
            except (ValueError, TypeError):
                pass
            self._update_live()

    # ── Rendering ──────────────────────────────────────────────────────

    def _update_live(self) -> None:
        """Push a fresh renderable to the Live context (if running)."""
        live = self._live
        if live is not None:
            try:
                live.update(self._build_renderable(), refresh=True)
            except Exception:
                pass

    def _build_renderable(self) -> RenderableType:
        """Compose the single-line status bar panel."""
        parts = []
        for i, phase in enumerate(self.PHASES):
            state_str = self._phase_states.get(phase, "pending")
            
            if state_str == "active":
                if phase == "Thinking":
                    ui_state = UIState.THINKING
                elif phase == "Running Tools":
                    ui_state = UIState.RUNNING
                else:
                    ui_state = UIState.STREAMING
            elif state_str == "done":
                ui_state = UIState.SUCCESS
            else:
                ui_state = UIState.IDLE
                
            parts.append(StatusLine(ui_state, context=phase, hide_verb=True))
            
            if i < len(self.PHASES) - 1:
                parts.append(Text(" → ", style=SEMANTIC.text_muted.to_rich_style()))
                
        if self._step is not None:
            parts.append(Text("  │  ", style=SEMANTIC.text_muted.to_rich_style()))
            parts.append(Text(f"Step {self._step}", style=SEMANTIC.accent.to_rich_style()))
            
        return SectionPanel(
            title="",
            content=Row(*parts),
            border_color=SEMANTIC.accent
        )
