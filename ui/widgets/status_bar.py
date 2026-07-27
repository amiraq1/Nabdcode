"""AgentStatusBar — phase-aware status bar replacing the Kinetic spinner.

Renders a single Rich Live line showing three pipeline phases
(Thinking → Running Tools → Generating) with per-phase state indicators,
and prints a compact stats summary on completion.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from core.kernel.events import bus


class AgentStatusBar:
    """Phase-aware status bar for the NABD agent pipeline.

    Phases: Thinking → Running Tools → Generating
    States: ○ pending  ● active (blue)  ✓ done (green)
    """

    PHASES = ["Thinking", "Running Tools", "Generating"]

    _SYMBOLS = {"pending": "○", "active": "●", "done": "✓"}

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()
        self._phase_states: dict[str, str] = {p: "pending" for p in self.PHASES}
        self._start_time: float | None = None
        self._tool_count: int = 0
        self._file_count: int = 0
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._live: Live | None = None
        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._lock = threading.Lock()
        self._wired: bool = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the Live display (idempotent)."""
        initial = self._build_renderable()
        with self._lock:
            if self._running:
                return
            self._running = True
            if self._start_time is None:
                self._start_time = time.time()
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
        """Tear down the Live context and join the spinner thread."""
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
        """Subscribe to EventBus events (idempotent)."""
        if self._wired:
            return
        bus.subscribe("llm_request_started", self._on_llm_start)
        bus.subscribe("tool_started", self._on_tool_start)
        bus.subscribe("file_read", self._on_file_event)
        bus.subscribe("file_written", self._on_file_event)
        bus.subscribe("file_modified", self._on_file_event)
        bus.subscribe("loop_completed", self._on_loop_completed)
        bus.subscribe("show_final_answer", self._on_final_answer)
        bus.subscribe("llm_token", self._on_token)
        self._wired = True

    # ── Event handlers ─────────────────────────────────────────────────

    def _on_llm_start(self, payload: Any) -> None:
        self.set_active("Thinking")

    def _on_tool_start(self, payload: Any) -> None:
        self.set_active("Running Tools")
        self.increment_tool()

    def _on_file_event(self, payload: Any) -> None:
        """Increment file count on file_read / file_written / file_modified."""
        self.increment_file()

    def _on_loop_completed(self, payload: Any) -> None:
        self.set_active("Generating")

    def _on_final_answer(self, payload: Any) -> None:
        self.set_complete()

    def _on_token(self, payload: Any) -> None:
        if isinstance(payload, dict):
            tok = payload.get("token", "")
            if tok:
                with self._lock:
                    self._output_tokens += max(1, len(str(tok)) // 4)

    # ── Public API ─────────────────────────────────────────────────────

    def set_active(self, phase: str) -> None:
        """Activate *phase*; mark all earlier phases done."""
        with self._lock:
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
        with self._lock:
            for p in self.PHASES:
                self._phase_states[p] = "done"
        self._update_live()
        self.stop()
        stats = self.get_stats()
        elapsed = stats["elapsed_time"]
        tools = stats["tool_count"]
        files = stats["file_count"]
        inp = self._input_tokens
        out = self._output_tokens
        self._console.print(
            f"✓ Done  {elapsed:.1f}s • {tools} tools • {files} files "
            f"• ↑{inp} ↓{out} tokens"
        )

    def get_stats(self) -> dict:
        """Return elapsed_time, tool_count, file_count."""
        elapsed = 0.0
        if self._start_time is not None:
            elapsed = time.time() - self._start_time
        return {
            "elapsed_time": elapsed,
            "tool_count": self._tool_count,
            "file_count": self._file_count,
        }

    def increment_tool(self) -> None:
        with self._lock:
            self._tool_count += 1
        self._update_live()

    def increment_file(self) -> None:
        with self._lock:
            self._file_count += 1
        self._update_live()

    # ── Rendering ──────────────────────────────────────────────────────

    def _spin_loop(self) -> None:
        """Refresh the Live display every 100ms."""
        while True:
            with self._lock:
                if not self._running:
                    return
                live = self._live
            if live is not None:
                try:
                    live.update(self._build_renderable(), refresh=True)
                except Exception:
                    pass
            time.sleep(0.10)

    def _update_live(self) -> None:
        """Push a fresh renderable to the Live context (if running)."""
        with self._lock:
            live = self._live
        if live is not None:
            try:
                live.update(self._build_renderable(), refresh=True)
            except Exception:
                pass

    def _build_renderable(self) -> RenderableType:
        """Compose the single-line status bar panel."""
        with self._lock:
            states = dict(self._phase_states)
        parts: list[str] = []
        for i, phase in enumerate(self.PHASES):
            sym = self._SYMBOLS.get(states.get(phase, "pending"), "○")
            if states.get(phase) == "active":
                parts.append(f"[bold cyan]{sym} {phase}[/]")
            elif states.get(phase) == "done":
                parts.append(f"[bold green]{sym} {phase}[/]")
            else:
                parts.append(f"[dim]{sym} {phase}[/]")
            if i < len(self.PHASES) - 1:
                parts.append("[dim] → [/]")
        content = "".join(parts)
        return Panel(
            Text.from_markup(content),
            border_style="cyan",
            padding=(0, 1),
        )
