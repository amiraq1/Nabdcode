"""main.py — NABD Agent OS TUI entry point.

Single-renderer architecture: Renderer owns stdout, PromptSession owns input.
"""

from __future__ import annotations

import os
import sys
import signal
import termios

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import ANSI

from engine.state import RuntimeState
from engine.loop import ExecutionLoop
from engine.events import bus
from engine.renderer import Renderer
from core.app_context import AppContext
from core.constants import TODO_DISCIPLINE


# ── Tool output summariser ─────────────────────────────────────────────────

def _summarise_tool(tool: str, args: dict, result) -> tuple[str, str, str]:
    """Return (badge, message, color) for a completed tool call."""
    if tool == "execute_shell":
        cmd = (args.get("command") or "")[:60]
        out = (getattr(result, "stdout", "") or "").strip()
        err = (getattr(result, "stderr", "") or "").strip()
        if getattr(result, "success", False):
            lines = len(out.splitlines()) if out else 0
            return ("EXEC", f"{cmd} ({lines} lines)", "cyan")
        else:
            snippet = (err or out).splitlines()[0][:80] if (err or out) else "unknown error"
            return ("ERROR", snippet, "red")

    if tool == "file_system":
        action = str(args.get("action", "")).lower()
        path = str(args.get("path", ""))
        if getattr(result, "success", False):
            if action in ("read", "list"):
                out = (getattr(result, "stdout", "") or "").strip()
                return ("READ", f"{path} ({len(out)} chars)", "cyan")
            elif action == "write":
                return ("WRITE", f"{path} updated", "green")
            elif action == "append":
                return ("WRITE", f"{path} +1 line", "green")
            elif action == "replace":
                return ("WRITE", f"{path} modified", "green")
            return ("DONE", f"{path}", "cyan")
        err = (getattr(result, "stderr", "") or "").splitlines()[0][:80]
        return ("ERROR", f"{path}: {err}", "red")

    if tool == "web_search":
        query = str(args.get("query", ""))[:40]
        if getattr(result, "success", False):
            out = (getattr(result, "stdout", "") or "").strip()
            count = out.count("[")
            return ("SEARCH", f'"{query}" ({count} results)', "cyan")
        return ("SEARCH", f'"{query}" — failed', "red")

    if tool == "search_memory":
        query = str(args.get("query", ""))[:40]
        if getattr(result, "success", False):
            out = (getattr(result, "stdout", "") or "").strip()
            count = out.count("[") if "[" in out else (1 if out else 0)
            return ("MEMORY", f'"{query}" ({count} hits)', "cyan")
        return ("MEMORY", f'"{query}" — failed', "red")

    return ("TOOL", tool, "cyan")


# ── Event Wiring ───────────────────────────────────────────────────────────

def wire_events(ctx: AppContext) -> None:
    """Subscribe all event handlers. Every output goes through renderer."""
    renderer = ctx.renderer
    metrics = ctx.metrics
    todo_manager = ctx.todo_manager

    _last_tool_args: dict = {}

    def _on_llm_started(p: dict) -> None:
        renderer.think_start("thinking")

    def _on_llm_completed(p: dict) -> None:
        renderer.think_end()
        metrics.record_api_call(duration=p.get("duration", 1.0))

    def _on_tool_started(p: dict) -> None:
        nonlocal _last_tool_args
        _last_tool_args = p.get("args", {})

    def _on_tool_completed(p: dict) -> None:
        tool = p.get("tool", "")
        args = _last_tool_args
        result = p.get("result")
        if result is None:
            return
        badge, msg, color = _summarise_tool(tool, args, result)
        renderer.badge_line(badge, msg, color)
        renderer.flush()

        # Render TODO list when the todo_write tool completes
        if tool == "todo_write" and todo_manager is not None:
            renderer.render_todos(todo_manager.all())
            renderer.flush()

    def _on_max_steps(p: dict) -> None:
        renderer.think_end()
        renderer.badge_line("PAUSED", "Max steps reached, continuing...", "yellow")
        renderer.flush()

    def _on_loop_error(p: dict) -> None:
        renderer.think_end()
        renderer.badge_line("ERROR", f"Engine: {p.get('error', 'unknown')}", "red")
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
    bus.subscribe("llm_request_completed", _on_llm_completed)
    bus.subscribe("tool_started", _on_tool_started)
    bus.subscribe("tool_completed", _on_tool_completed)
    bus.subscribe("loop_max_steps_reached", _on_max_steps)
    bus.subscribe("loop_error", _on_loop_error)
    bus.subscribe("llm_provider_failover", _on_provider_failover)
    bus.subscribe("deep_plan", _on_deep_plan)
    bus.subscribe("deep_exec", _on_deep_exec)
    bus.subscribe("deep_review", _on_deep_review)
    bus.subscribe("deep_replan", _on_deep_replan)
    bus.subscribe("hitl_triggered", _on_hitl_triggered)
    bus.subscribe("clarify_triggered", _on_clarify_triggered)


# ── System Setup ───────────────────────────────────────────────────────────

# setup_system migrated to core/app_context.py: AppContext.build()


# ── Main Loop ──────────────────────────────────────────────────────────────

def main() -> None:
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

    # One-time splash
    try:
        import nabd_logo  # type: ignore[import-untyped]
        nabd_logo.draw()
    except Exception:
        pass

    ctx = AppContext.build()
    deleted = ctx.session_manager.enforce_retention_policy(ctx.config.max_sessions)

    state = RuntimeState(session_id=ctx.session_manager.session_id, max_steps=50)
    wire_events(ctx)

    # Graceful shutdown
    def _shutdown_handler(signum: int, frame: object) -> None:
        ctx.renderer.shutdown()
        ctx.session_manager.messages = state.get_messages()
        ctx.session_manager.save()
        ctx.memory_manager.close()
        ctx.logger.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGHUP, _shutdown_handler)

    base_inst = (
        "You are an advanced Autonomous Agent running on a Linux environment.\n"
        "CRITICAL RULE: You must respond ONLY and exclusively in English.\n"
        "Keep all terminal outputs in clean, standard English.\n"
        "\n"
        "If a task requires filesystem inspection, code analysis, shell execution, or memory retrieval, "
        "you MUST use the appropriate tool.\n"
        "\n"
        "Never infer or invent project names, files, architectures, test frameworks, or statistics.\n"
        "\n"
        "If a required tool fails, explicitly report the failure and stop.\n"
        "\n"
        "Producing fabricated analysis is considered a failed task.\n"
        "\n"
        "Every factual statement must be backed by either:\n"
        "- a tool result,\n"
        "- a file that was actually read,\n"
        "- or previous verified memory.\n"
        "\n"
        "Otherwise respond: \"I don't have sufficient evidence.\""
        + TODO_DISCIPLINE
    )
    state.append_message({"role": "system", "content": base_inst})

    input_session = PromptSession(
        history=InMemoryHistory(),
        mouse_support=False,
    )

    # Flush any setup output before first prompt
    ctx.renderer.flush()

    while True:
        try:
            user_input = input_session.prompt(
                ANSI("\033[36m❯ \033[0m")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break

        if user_input.lower() == "clear":
            # Replace the prompt line with a background-highlighted version
            sys.stdout.write(f"\r\033[48;5;236m\033[36m❯ clear\033[0m\n")
            sys.stdout.flush()
            state.set_messages([{"role": "system", "content": base_inst}])
            state.reset_step_count()
            continue

        # Replace the prompt_toolkit line with a background-highlighted version
        # so the user's input is visually distinct from the agent response.
        sys.stdout.write(f"\r\033[48;5;236m\033[36m❯ {user_input}\033[0m\n")
        sys.stdout.flush()

        state.reset_step_count()
        engine = ExecutionLoop(state=state, max_output_len=ctx.config.max_output)

        fd = sys.stdin.fileno()
        old_termios = None
        try:
            old_termios = termios.tcgetattr(fd)
            new = list(old_termios)
            new[3] = new[3] & ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSANOW, new)
            engine.run(user_input)
        except KeyboardInterrupt:
            ctx.renderer.think_end()
            ctx.renderer.flush()
        except Exception as exc:
            # Error already rendered by _on_loop_error via event bus
            ctx.logger.error(f"Execution failed: {exc}")
        finally:
            if old_termios is not None:
                termios.tcsetattr(fd, termios.TCSANOW, old_termios)
            try:
                termios.tcflush(fd, termios.TCIFLUSH)
            except Exception:
                pass

        # Save session
        ctx.session_manager.messages = state.get_messages()
        ctx.session_manager.save()

        # Print assistant response — no badge, just content
        last_msg = state.get_last_message()
        if last_msg and last_msg.get("role") == "assistant":
            for line in last_msg.get("content", "").splitlines():
                ctx.renderer.agent_text(line)
            ctx.renderer.flush()


if __name__ == "__main__":
    main()
