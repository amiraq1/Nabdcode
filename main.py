"""
main.py — NABD Agent OS TUI entry point.

Renderer ownership
──────────────────
    Renderer (engine/renderer.py) owns stdout.
    PromptSession owns the input line.
    No background threads write to the terminal.
    All event output is buffered and flushed atomically.
"""

from __future__ import annotations

import os
import sys
import atexit
import signal
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import ANSI

from engine.state import RuntimeState
from engine.loop import ExecutionLoop
from engine.tool_registry import registry
from engine.events import bus
from engine.renderer import Renderer, layout_margin
from tools import ShellTool, FileSystemTool, WebSearchTool, SearchMemoryTool
from core.session import SessionManager
from core.logger import Logger
from core.metrics import MetricsEngine
from core.config import AgentConfig
from core.utils import truncate
from core.memory import MemoryManager


# ============================================================================
# Event Wiring — Single rendering pipeline
# ============================================================================

def wire_events(renderer: Renderer, metrics: MetricsEngine) -> None:
    """
    Subscribe all event handlers to the EventBus.

    Every handler calls renderer.print() / renderer.badge_line() / etc.
    and ends with renderer.flush().

    Architecture property:
        All output goes through one Renderer instance.
        No print() calls, no sys.stdout.write() calls outside this module.
    """

    def _on_llm_started(p: dict) -> None:
        step = p.get("step", 0) + 1
        renderer.separator()
        renderer.step_header(step)
        renderer.spinner_start()
        renderer.flush()

    def _on_llm_completed(p: dict) -> None:
        renderer.spinner_stop()
        metrics.record_api_call(duration=p.get("duration", 1.0))
        dur = p.get("duration", 0.0)
        chars = p.get("length", 0)
        renderer.status_line(
            "Thought structured",
            "",
            f"({chars} chars) in {dur:.2f}s [ctrl+o to expand]",
        )
        renderer.flush()

    def _on_tool_started(p: dict) -> None:
        tool = p.get("tool", "")
        args = p.get("args", {})
        target = (
            args.get("path")
            or args.get("command")
            or args.get("query")
            or "system"
        )
        renderer.print_margin(
            f"\033[1;37;45m ◆ {tool.upper()}ING... \033[0m \033[90m| Ready\033[0m"
        )
        renderer.badge_line("", tool, args, truncate(str(target), 28))
        renderer.flush()

    def _on_tool_completed(p: dict) -> None:
        success = p.get("success", False)
        code = p.get("returncode", -1)
        diff_text = p.get("diff", "")
        result_obj = p.get("result")
        output_text = (
            getattr(result_obj, "output", "")
            or p.get("output", "")
            or getattr(result_obj, "stdout", "")
        )
        status_badge = "\033[1;37;42m OK \033[0m" if success else "\033[1;37;41m FAIL \033[0m"

        if diff_text:
            renderer.diff_block(diff_text)
        elif output_text:
            lines = str(output_text).splitlines()
            renderer.text_block(lines)

        renderer.status_line("", status_badge, f"Code: {code}")
        renderer.flush()

    def _on_todo_list(p: dict) -> None:
        todos = p.get("todos", [])
        if todos:
            renderer.todo_block(todos)
            renderer.flush()

    def _on_max_steps(p: dict) -> None:
        renderer.print_margin("\033[1;37;41m PAUSED \033[0m Max steps reached!")
        renderer.flush()

    def _on_loop_error(p: dict) -> None:
        renderer.print_margin(
            f"\033[1;37;41m ERROR \033[0m Engine error: {p.get('error', 'Unknown')}"
        )
        renderer.flush()

    def _on_provider_failover(p: dict) -> None:
        provider = p.get("provider", "?")
        error = p.get("error", "?")
        renderer.print_margin(
            f"\033[1;33m [FAILOVER] Provider '{provider}' failed ({error}). Switching...\033[0m"
        )
        renderer.flush()

    bus.subscribe("llm_request_started", _on_llm_started)
    bus.subscribe("llm_request_completed", _on_llm_completed)
    bus.subscribe("tool_started", _on_tool_started)
    bus.subscribe("tool_completed", _on_tool_completed)
    bus.subscribe("show_todo_list", _on_todo_list)
    bus.subscribe("loop_max_steps_reached", _on_max_steps)
    bus.subscribe("loop_error", _on_loop_error)
    bus.subscribe("llm_provider_failover", _on_provider_failover)


# ============================================================================
# System Setup
# ============================================================================

def setup_system() -> tuple[SessionManager, Logger, MetricsEngine, AgentConfig, MemoryManager, Renderer]:
    config = AgentConfig()
    session_mgr = SessionManager(root=config.session_dir)
    logger = Logger(log_dir=config.log_dir)
    metrics = MetricsEngine()
    memory_mgr = MemoryManager(db_path=os.path.join(config.root_dir, "workspace_memory.db"))
    renderer = Renderer()

    for tool_cls in [ShellTool, FileSystemTool, WebSearchTool, SearchMemoryTool]:
        tool = (
            tool_cls(workspace=config.root_dir)
            if tool_cls is FileSystemTool
            else SearchMemoryTool(memory_manager=memory_mgr)
            if tool_cls is SearchMemoryTool
            else tool_cls()
        )
        try:
            registry.register(tool)
        except ValueError:
            pass

    atexit.register(renderer.shutdown)
    atexit.register(logger.shutdown)
    atexit.register(memory_mgr.close)
    return session_mgr, logger, metrics, config, memory_mgr, renderer


# ============================================================================
# Main Loop
# ============================================================================

def main() -> None:
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

    # Splash — one-time print before renderer owns the screen
    try:
        import nabd_logo  # type: ignore[import-untyped]
        nabd_logo.draw()
    except Exception:
        pass

    session_mgr, logger, metrics, config, memory_mgr, renderer = setup_system()
    deleted = session_mgr.enforce_retention_policy(config.max_sessions)

    state = RuntimeState(session_id=session_mgr.session_id, max_steps=50)
    wire_events(renderer, metrics)

    # ── Graceful shutdown ───────────────────────────────────────────────────
    def _shutdown_handler(signum: int, frame: object) -> None:
        renderer.print_margin(
            f"\033[1;37;41m SHUTDOWN \033[0m Signal {signum} received. Saving state..."
        )
        renderer.flush()
        session_mgr.messages = state.get_messages()
        session_mgr.save()
        memory_mgr.close()
        logger.shutdown()
        renderer.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGHUP, _shutdown_handler)

    if deleted:
        renderer.print_margin(f"[INFO] Cleaned {deleted} old session(s).")
        renderer.flush()
    renderer.print_margin(f"[+] Session Initialized: {session_mgr.session_id}")
    renderer.flush()

    base_inst = (
        "You are an advanced Autonomous Agent running on a Linux environment.\n"
        "CRITICAL RULE: You must respond ONLY and exclusively in English. \n"
        "Never use Arabic characters or any other RTL language in your thoughts, "
        "plans, or responses. \n"
        "Keep all terminal outputs in clean, standard English."
    )
    state.append_message({"role": "system", "content": base_inst})

    input_session = PromptSession(
        history=InMemoryHistory(),
        mouse_support=True,
    )

    while True:
        try:
            user_input = input_session.prompt(
                ANSI("\n\033[1;37;45m USER \033[0m ")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            renderer.print_margin("Exiting...")
            renderer.flush()
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break

        if user_input.lower() == "clear":
            state.set_messages([{"role": "system", "content": base_inst}])
            state.reset_step_count()
            renderer.print_margin("[+] Local session memory cleared.")
            renderer.flush()
            continue

        renderer.user_prompt_panel(user_input)
        renderer.separator()
        renderer.print_margin(
            "\033[1;37;44m PLAN \033[0m \033[32mAnalyzing request...\033[0m"
        )
        renderer.flush()

        state.reset_step_count()
        engine = ExecutionLoop(state=state, max_output_len=config.max_output)

        try:
            engine.run(user_input)

            session_mgr.messages = state.get_messages()
            session_mgr.save()

            last_msg = state.get_last_message()
            if last_msg and last_msg.get("role") == "assistant":
                padding_left, _ = layout_margin()
                renderer.print_margin("\033[1;37;42m AGENT \033[0m")
                for line in last_msg.get("content", "").splitlines():
                    renderer.print_margin(line)
                renderer.flush()

        except KeyboardInterrupt:
            renderer.print_margin("[!] Execution interrupted by user.")
            renderer.flush()
        except Exception as exc:
            msg = f"[SYSTEM ERROR] {exc}"
            renderer.print_margin(f"\033[1;37;41m {msg} \033[0m")
            renderer.flush()
            logger.error(f"Execution failed: {exc}")


if __name__ == "__main__":
    main()
