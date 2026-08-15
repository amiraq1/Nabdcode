"""Event wiring module for NABD OS (ARCH-5 extracted)."""
from __future__ import annotations
import time
# ── Event Wiring ───────────────────────────────────────────────────────────
from ui.cc_style import status_compact_line
from engine.ui_theme import thought_summary, select_status_verb

_step_start_time: float | None = None
_timed_step: object = None

def _mark_step(step: object) -> None:
    """UI-CC-9b: بدء التوقيت لكل خطوة جديدة (المسار الحي)."""
    global _step_start_time, _timed_step
    if _step_start_time is None or _timed_step != step:
        _step_start_time = time.monotonic()
        _timed_step = step

def _elapsed_for(step: object) -> float:
    _mark_step(step)
    return time.monotonic() - (_step_start_time or time.monotonic())

def wire_events(ctx: "AppContext") -> dict:  # noqa: F821 — forward ref
    """Subscribe all event handlers. Every output goes through renderer."""
    import main
    status_bar = main.status_bar
    from core.kernel.events import bus
    from engine.ui_theme import map_tool_to_badge

    renderer = ctx.renderer
    metrics = ctx.metrics
    todo_manager = ctx.todo_manager

    _last_tool_args: dict = {}
    _last_stage: str = "init"
    _last_tool_name: str = ""
    _turn_index: int = 0

    _token_buf: str = ""
    _held_buf: str = ""
    _tool_was_used: bool = False

    def _on_llm_started(p: dict) -> None:
        nonlocal _turn_index, _token_buf, _held_buf, _tool_was_used
        _token_buf = ""
        _held_buf = ""
        _tool_was_used = False  # Stage 2: reset per-turn tool tracking
        _turn_index += 1
        # UI-CC-7: inline compact status line replaces the live SectionPanel
        # box that was rendered by the status bar (protected file untouched).
        from rich.console import Console
        Console().print(status_compact_line(
            step=_turn_index, elapsed=_elapsed_for(_turn_index),
            thinking=True, tools=False, generating=False,
        ))

    def _on_llm_token(p: dict) -> None:
        # When the interactive TerminalVisualizer owns the TTY (REPL mode), it
        # is the single renderer and wire_events yields to it. In one-shot mode
        # the visualizer is built without listeners, so this flag stays False
        # and wire_events is the sole renderer. Exactly one renderer per mode.
        if getattr(bus, "_on_tool_completed_active", False):
            return
        nonlocal _token_buf, _held_buf
        content = p.get("token", "")
        # Buffer intermediate tokens locally and DISCARD — never stream to
        # stdout. Only the final answer (rendered separately after engine.run()
        # returns) may reach stdout. This guarantees no reasoning, planning,
        # scratchpad, or chain-of-thought text leaks to the terminal.
        _token_buf += content
        stripped = _token_buf.lstrip()
        if stripped.startswith("{") or stripped.startswith("final_answer"):
            return
        if "final_answer".startswith(stripped):
            _held_buf += content
            return

    def _on_llm_completed(p: dict) -> None:
        # UI-CC-7: all phases done — compact line marks completion.
        from rich.console import Console
        from rich.text import Text
        elapsed = p.get("duration") or _elapsed_for(_turn_index)
        # Stage 2: only mark Tools done if a tool was actually started this turn.
        Console().print(status_compact_line(
            step=_turn_index, elapsed=elapsed,
            thinking=True, tools=_tool_was_used, generating=True,
        ))
        # Surface duration only: reasoning content remains intentionally hidden.
        # Stage 1: wrap ANSI string in Text.from_ansi so Rich renders it as
        # styled Text, not as raw escape codes passed through as a plain string.
        Console().print(Text.from_ansi(
            thought_summary(elapsed, expand_hint="activity summary")
        ))
        renderer.flush()
        metrics.record_api_call(duration=p.get("duration", 1.0))

    def _on_tool_started(p: dict) -> None:
        if getattr(bus, "_on_tool_completed_active", False):
            return
        nonlocal _last_tool_args, _last_tool_name, _tool_was_used
        tool = p.get("tool") or p.get("name", "")
        args = p.get("args") or {}
        _last_tool_args = args
        _last_tool_name = tool
        _tool_was_used = True  # Stage 2: mark Tools phase as entered
        renderer.tool_start(tool, args)
        renderer.flush()

    def _on_tool_completed(p: dict) -> None:
        if getattr(bus, "_on_tool_completed_active", False):
            return
        nonlocal _last_stage
        result = p.get("result")
        if result is None:
            return
        tool = p.get("tool") or ""
        success = p.get("success", getattr(result, "success", False))
        output = (getattr(result, "stdout", "") or "").strip()
        stderr = (getattr(result, "stderr", "") or "").strip()
        diff_text = p.get("diff") or getattr(result, "diff", "")
        kind = map_tool_to_badge(tool, _last_tool_args)

        if kind == "EDIT":
            _last_stage = "edit"
        elif kind == "SHELL":
            _last_stage = "shell"
        elif kind == "READ":
            _last_stage = "read"

        # Build summary line
        summary = ""
        if not success:
            snippet = (stderr or output).splitlines()[0][:80] if (stderr or output) else "failed"
            summary = snippet
        elif kind == "READ" and output:
            n = len(output.splitlines())
            summary = f"{n} lines"
        elif kind == "SHELL" and output:
            n = len(output.splitlines())
            cmd = _last_tool_args.get("command", "")[:40]
            summary = f"{cmd} ({n} lines)"
        elif kind in ("SEARCH", "MEMORY") and output:
            count = output.count("[")
            summary = f"{count} results"
        elif kind == "TASK":
            metadata = getattr(result, "metadata", {}) or {}
            node_id = str(metadata.get("task_graph_task_id", "")).strip()
            graph_status = str(metadata.get("task_graph_status", "untracked")).strip()
            evidence_ids = metadata.get("evidence_ids", []) or []
            role = str(_last_tool_args.get("role", "research")).strip().lower() or "research"
            node_part = f"node={node_id}" if node_id else "no graph node"
            summary = f"{role} · {graph_status} · {node_part} · evidence={len(evidence_ids)}"

        renderer.tool_end(
            tool,
            success=success,
            output=output,
            summary=summary,
            diff=diff_text if kind == "EDIT" and diff_text else "",
        )
        renderer.status_snapshot(select_status_verb(_last_stage, tool, _turn_index))
        renderer.flush()

        # Render TODO list when the todo_write tool completes
        if tool == "todo_write" and todo_manager is not None:
            items = [
                {"content": it.text, "status": it.status.value}
                for it in todo_manager.all()
            ]
            renderer.todos(items)
            renderer.flush()

    def _on_max_steps(p: dict) -> None:
        renderer.think_end()
        renderer.error_badge("PAUSED", "Max steps reached, continuing...")
        renderer.flush()

    def _on_loop_error(p: dict) -> None:
        renderer.think_end()
        renderer.error_badge("ENGINE", p.get("error", "unknown"))
        renderer.flush()

    def _on_loop_completed(p: dict) -> None:
        # The engine terminated the turn (connection_lost / budget_exhausted /
        # goal_not_met / etc.). Surface the reason/error to the user instead of
        # returning silently to the prompt.
        reason = p.get("reason", "completed")
        output = p.get("output", "")
        renderer.think_end()
        if reason in ("connection_lost",) or not output or isinstance(output, Exception):
            err_msg = str(output) if output else f"Agent stopped: {reason}. Check network/OpenRouter key & credit."
            renderer.error_badge("ENGINE", err_msg)
        else:
            # ❌ الكود القديم الذي يسبب ظهور صندوقين (Double-Render): تم تعطيله
            pass
        renderer.flush()

    def _on_provider_failover(p: dict) -> None:
        prov = p.get("provider", "?")
        renderer.dim_line(f"retrying {prov}...")
        renderer.flush()

    def _on_deep_plan(p: dict) -> None:
        renderer.badge_line("PLAN", "Analyzing task & structuring execution steps...", "cyan")
        renderer.flush()

    def _on_deep_exec(p: dict) -> None:
        renderer.badge_line("EXEC", "Running plan steps sequentially...", "green")
        renderer.flush()

    def _on_deep_review(p: dict) -> None:
        renderer.badge_line("REVIEW", "Reflecting on final output quality...", "yellow")
        renderer.flush()

    def _on_deep_replan(p: dict) -> None:
        renderer.badge_line("RE-PLAN", "Review failed. Injecting critique & re-planning...", "red")
        renderer.flush()

    def _on_hitl_triggered(p: dict) -> None:
        step = p.get("step", "")
        renderer.badge_line("HITL", f"Human approval requested for sensitive step: '{step}'", "yellow")
        renderer.flush()

    def _on_clarify_triggered(p: dict) -> None:
        question = p.get("question", "")
        renderer.badge_line("CLARIFY", f"Interactive steering required: {question}", "yellow")
        renderer.flush()

    bus.subscribe("llm_request_started", _on_llm_started)
    # UI-CC-7: keep the bar listening on the bus (protected contract) but
    # do NOT start() it — the inline compact line replaces the live box.
    status_bar.wire()
    bus.subscribe("llm_token", _on_llm_token)
    bus.subscribe("llm_request_completed", _on_llm_completed)
    bus.subscribe("tool_started", _on_tool_started)
    bus.subscribe("tool_completed", _on_tool_completed)
    bus.subscribe("loop_max_steps_reached", _on_max_steps)
    bus.subscribe("loop_error", _on_loop_error)
    bus.subscribe("loop_completed", _on_loop_completed)
    bus.subscribe("llm_provider_failover", _on_provider_failover)
    bus.subscribe("deep_plan", _on_deep_plan)
    bus.subscribe("deep_exec", _on_deep_exec)
    bus.subscribe("deep_review", _on_deep_review)
    bus.subscribe("deep_replan", _on_deep_replan)
    bus.subscribe("hitl_triggered", _on_hitl_triggered)
    bus.subscribe("clarify_triggered", _on_clarify_triggered)


