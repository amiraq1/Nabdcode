"""main.py — NABD Agent OS TUI entry point.

Single-renderer architecture: Renderer owns stdout, PromptSession owns input.
"""

from __future__ import annotations

import json
import os
import sys


# ── Tool output summariser ─────────────────────────────────────────────────

def _summarise_tool(tool: str, args: dict, result) -> tuple[str, str, str]:
    """Return (badge, message, color) for a completed tool call.

    Used only as fallback; UI theme methods (tool_start/tool_end) are
    the primary rendering path.
    """
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


def _extract_final_answer_text(raw: str) -> str:
    """UI-layer helper: unwrap a final_answer tool call into clean text.

    When the ExecutionLoop terminates via the smolagents ``final_answer``
    convention, the last assistant message is the raw tool-call JSON
    (e.g. ``{"tool": "final_answer", "args": {"answer": "Hi!"}}``). Rendering
    that verbatim leaks the JSON blob into the TUI. This strictly-visual
    helper parses it and returns only ``args["answer"]``.

    Non-final_answer content (normal prose, or prose with embedded JSON) is
    returned unchanged, so default rendering is preserved. Any parse failure
    also falls back to the original text — this never mutates core state or
    raises, keeping it safe for the rendering path only.
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw
    if not isinstance(payload, dict):
        return raw
    if payload.get("tool") != "final_answer":
        return raw
    args = payload.get("args")
    if not isinstance(args, dict):
        return raw
    answer = args.get("answer")
    if not isinstance(answer, str):
        return raw
    return answer


# ── Event Wiring ───────────────────────────────────────────────────────────

def wire_events(ctx: AppContext) -> dict:
    """Subscribe all event handlers. Every output goes through renderer."""
    from engine.events import bus
    from engine.ui_theme import map_tool_to_badge, select_status_verb

    renderer = ctx.renderer
    metrics = ctx.metrics
    todo_manager = ctx.todo_manager

    _last_tool_args: dict = {}
    _last_stage: str = "init"
    _last_tool_name: str = ""
    _turn_index: int = 0

    _token_buf: str = ""
    _held_buf: str = ""

    def _on_llm_started(p: dict) -> None:
        nonlocal _turn_index, _token_buf, _held_buf
        _token_buf = ""
        _held_buf = ""
        _turn_index += 1
        verb = select_status_verb(stage=_last_stage, last_tool=_last_tool_name, turn_index=_turn_index)
        renderer.status_start(verb)
        renderer.thought_start()

    def _on_llm_token(p: dict) -> None:
        nonlocal _token_buf, _held_buf
        content = p.get("token", "")
        _token_buf += content
        stripped = _token_buf.lstrip()
        if stripped.startswith("{") or stripped.startswith("final_answer"):
            return
        if "final_answer".startswith(stripped):
            _held_buf += content
            return
        to_print = _held_buf + content
        _held_buf = ""
        renderer.stream_chunk(to_print)

    def _on_llm_completed(p: dict) -> None:
        renderer.thought_end()
        renderer.flush()
        metrics.record_api_call(duration=p.get("duration", 1.0))

    def _on_tool_started(p: dict) -> None:
        nonlocal _last_tool_args, _last_tool_name
        tool = p.get("tool") or p.get("name", "")
        args = p.get("args") or {}
        _last_tool_args = args
        _last_tool_name = tool
        renderer.tool_start(tool, args)
        renderer.flush()

    def _on_tool_completed(p: dict) -> None:
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

        renderer.tool_end(
            tool,
            success=success,
            output=output,
            summary=summary,
            diff=diff_text if kind == "EDIT" and diff_text else "",
        )
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
        # goal_not_met / etc.). Surface the reason to the user instead of
        # returning silently to the prompt — otherwise a fully exhausted
        # provider chain leaves the user staring at a blinking cursor with no
        # explanation of why the agent went mute.
        reason = p.get("reason", "completed")
        output = p.get("output", "")
        renderer.think_end()
        if reason in ("connection_lost",) or not output:
            renderer.error_badge(
                "ENGINE",
                output or f"Agent stopped: {reason}. Check network/OpenRouter key & credit.",
            )
        else:
            rendered = _extract_final_answer_text(output)
            if rendered and rendered.strip():
                for line in rendered.splitlines():
                    renderer.agent_text(line)
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


# ── System Setup ───────────────────────────────────────────────────────────

# setup_system migrated to core/app_context.py: AppContext.build()


# ── Main Loop ──────────────────────────────────────────────────────────────

def main() -> None:
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

    # Fast check for basic flags before loading heavy modules or initializing agents
    if any(flag in sys.argv[1:] for flag in ("--version", "-v")):
        sys.stdout.write("Nabd OS (nabdcode) v1.0.0\n")
        sys.exit(0)
    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        sys.stdout.write(
            "NABD Agent OS — Mobile-first AI CLI agent for Termux.\n\n"
            "Usage:\n"
            "  nabdcode [options] [query...]\n"
            "  python3 main.py [options] [query...]\n\n"
            "Options:\n"
            "  -h, --help       Show this help message and exit\n"
            "  -v, --version    Show program version and exit\n"
        )
        sys.exit(0)

    import signal
    import termios

    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.formatted_text import ANSI, HTML

    from engine.state import RuntimeState
    from engine.loop import ExecutionLoop, ToolRequiredError
    from engine.events import bus
    from ui.repl_termux import TerminalVisualizer
    from core.app_context import AppContext
    from core.constants import TODO_DISCIPLINE
    from core.sanitize import sanitize
    from core.parser import normalize

    # One-time splash
    try:
        import nabd_logo  # type: ignore[import-untyped]
        nabd_logo.draw()
    except Exception:
        pass

    ctx = AppContext.build()
    state = RuntimeState(session_id=ctx.session_manager.session_id, max_steps=50)
    deleted = ctx.session_manager.enforce_retention_policy(ctx.config.max_sessions)

    # Restore todos + evidence from the latest session (v2+ only) — read JSON
    # directly to avoid mutating session_manager's identity.
    _latest_id = ctx.session_manager.get_latest_session(ctx.config.session_dir)
    if _latest_id:
        _latest_path = ctx.config.session_dir / f"{_latest_id}.json"
        if _latest_path.exists():
            try:
                _data = json.loads(_latest_path.read_text(encoding="utf-8"))
                if isinstance(_data, dict):
                    _todos = _data.get("todos")
                    if isinstance(_todos, list):
                        ctx.todo_manager.restore(_todos)
                    _evidence_records = _data.get("evidence_records")
                    if isinstance(_evidence_records, dict):
                        ctx.evidence_log.restore({"records": _evidence_records})
            except Exception as exc:
                sys.stderr.write(f"[Warning] Session restore failed: {exc}\n")
    wire_events(ctx)
    visualizer = TerminalVisualizer(event_bus=bus, state=state)

    # Isolate provider state file per session
    from llm_router import router as _provider_router
    _provider_router.set_state_key(ctx.session_manager.session_id[:12])

    # Graceful shutdown
    def _shutdown_handler(_signum: int, _frame: object) -> None:
        ctx.renderer.shutdown()
        ctx.session_manager.messages = state.get_messages()
        ctx.session_manager.todos = ctx.todo_manager.to_serializable()
        ctx.session_manager.evidence = ctx.evidence_log.to_serializable().get("records", [])
        ctx.session_manager.save()
        ctx.memory_manager.close()
        ctx.logger.shutdown()
        visualizer.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGHUP, _shutdown_handler)

    state = RuntimeState(session_id=ctx.session_manager.session_id, max_steps=50)

    # ── Helpers for ToolRequiredError path ────────────────────────────────

    def _cleanup_after_streamed_failure(state: RuntimeState,
                                        ctx: AppContext,
                                        exc: ToolRequiredError) -> None:
        """After streaming output, the verifier rejected the answer.
        Strip the fabricated response, add a newline separator so the
        rejection message isn't glued to the last token, and render
        the verifier's message to the user.
        """
        msgs = state.get_messages()
        if msgs and msgs[-1].get("role") == "assistant":
            state.set_messages(msgs[:-1])
        ctx.logger.error(f"ToolRequiredError: {exc}")
        ctx.renderer.think_end()
        ctx.renderer.verifier_reject(str(exc))
        ctx.renderer.flush()

    base_inst = (
        "You are an advanced Autonomous Agent running on a Linux environment.\n"
        "CRITICAL RULE: Respond ONLY in English.\n"
        "\n"
        "=== TASK CLASSIFICATION - APPLY THIS FIRST ===\n"
        "A) GENERAL / GREETINGS / MATH / FACTS / COUNTRIES (e.g. 'hi', 'hello', 'iraq', '1+1', 'what is Iraq?'):\n"
        " - Answer DIRECTLY from your own knowledge.\n"
        " - DO NOT call file_system, web_search, search_memory, todo_write, execute_shell, or ANY tool.\n"
        " - NEVER say 'I don\\'t have information' or 'I don\\'t have sufficient evidence' for this category. You DO have the answer.\n"
        " - Examples: 'hi' -> 'Hello! How can I help?'; 'iraq' -> 2-3 sentences about Iraq; '1+1' -> '2'.\n"
        "\n"
        "B) CODEBASE / FILESYSTEM / PROJECT TASKS (e.g. 'read main.py', 'how many files', 'run tests', 'inspect engine/loop.py'):\n"
        " - You MUST use the appropriate tool.\n"
        " - Every factual statement about codebase/filesystem must be backed by tool output, file read, or verified memory.\n"
        " - If after using tools you still lack proof, state: \"I don\\'t have sufficient evidence.\"\n"
        " - Never invent file names, architectures, or statistics.\n"
        "\n"
        "BEHAVIOR:\n"
        "- Max 2 thoughts before action.\n"
        "- For complex calculations you MAY use execute_shell python3 -c \"print(...)\" but simple math answer directly.\n"
        + TODO_DISCIPLINE
    )
    state.append_message({"role": "system", "content": base_inst})

    plan_mode: bool = False

    from prompt_toolkit.key_binding import KeyBindings

    def _bottom_toolbar():
        if plan_mode:
            return ANSI(
                f"\033[38;2;250;204;21mplan mode\033[0m "
                f"\033[2m[shift+tab]\033[0m  "
                f"\033[2m? for shortcuts\033[0m"
            )
        return ANSI(
            f"\033[38;2;167;139;250m» accept edits on\033[0m "
            f"\033[2m[shift+tab]\033[0m  "
            f"\033[2m? for shortcuts\033[0m"
        )

    bindings = KeyBindings()

    @bindings.add("c-o")
    def _on_ctrl_o(event) -> None:
        """Expand the last collapsed output block."""
        expanded = ctx.renderer.expand_last()
        if expanded:
            sys.stdout.write(f"\r{'─' * 40}\n")
            for line in expanded.splitlines():
                sys.stdout.write(f"  {line}\n")
            sys.stdout.flush()

    @bindings.add("s-tab")
    def _on_shift_tab(event) -> None:
        nonlocal plan_mode
        plan_mode = not plan_mode

    input_session = PromptSession(
        history=InMemoryHistory(),
        mouse_support=False,
        # Single-line mode: 'Enter' always submits immediately, even when the
        # pasted text contains newlines. Without this, prompt_toolkit defaults
        # to auto-multiline and a paste with newlines traps the user in the
        # "accept edits on [shift+tab]" editor (Enter just inserts newlines).
        multiline=False,
        key_bindings=bindings,
    )

    # Flush any setup output before first prompt
    ctx.renderer.flush()

    try:
        while True:
            try:
                user_input = input_session.prompt(
                    ANSI("\033[36m❯ \033[0m"),
                    bottom_toolbar=_bottom_toolbar,
                    placeholder=HTML('<style fg="#555">Ask your question...</style>'),
                ).strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit"):
                break

            if user_input.lower() in ("clear", "/clear", "/reset", "/c"):
                # Replace the prompt line with a background-highlighted version
                sys.stdout.write(f"\r\033[48;5;236m\033[36m❯ {user_input}\033[0m\n")
                sys.stdout.flush()
                state.clear_context()
                state.set_messages([{"role": "system", "content": base_inst}])
                if hasattr(ctx.evidence_log, "clear"):
                    ctx.evidence_log.clear()
                elif isinstance(ctx.evidence_log, list):
                    ctx.evidence_log.clear()
                if hasattr(ctx.todo_manager, "clear"):
                    ctx.todo_manager.clear()
                try:
                    (get_workspace_root() / CHECKPOINT_FILENAME).unlink(missing_ok=True)
                except Exception:
                    pass
                sys.stdout.write("\n\033[92m✨ [System] Context and history have been cleared. Ready for a new task!\033[0m\n\n")
                sys.stdout.flush()
                continue

            # Replace the prompt_toolkit line with a background-highlighted version
            # so the user's input is visually distinct from the agent response.
            safe_display = sanitize(user_input)
            sys.stdout.write(f"\r\033[48;5;236m\033[36m❯ {safe_display}\033[0m\n")
            sys.stdout.flush()

            clean_prompt = normalize(user_input)[:10000]

            state.reset_step_count()
            engine = ExecutionLoop(
                state=state,
                max_output_len=ctx.config.max_output,
                evidence_log=ctx.evidence_log,
                logger=ctx.logger,
            )

            fd = sys.stdin.fileno()
            old_termios = None
            try:
                old_termios = termios.tcgetattr(fd)
                new = list(old_termios)
                new[3] = new[3] & ~termios.ECHO
                termios.tcsetattr(fd, termios.TCSANOW, new)
                engine.run(clean_prompt)
            except KeyboardInterrupt:
                ctx.renderer.think_end()
                ctx.renderer.flush()
            except ToolRequiredError as exc:
                # ToolRequiredError: The LLM answered without using required tools.
                # Strip the fabricated response, add newline separator after any
                # partial streaming output, and show the verifier's rejection.
                _cleanup_after_streamed_failure(state, ctx, exc)
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

            # Save session — messages, todos, evidence audit trail
            ctx.session_manager.messages = state.get_messages()
            ctx.session_manager.todos = ctx.todo_manager.to_serializable()
            ctx.session_manager.evidence = ctx.evidence_log.to_serializable().get("records", [])
            ctx.session_manager.save()

            # NOTE: The assistant response is already rendered inside its
            # green panel by the `show_final_answer` event (on_final_answer in
            # ui/repl_termux.py) for every exit path — streaming, static, and
            # fallback. Re-printing it here would duplicate the text as raw
            # output outside the panel, so the manual fallback print is
            # intentionally removed.

    finally:
        visualizer.stop()


if __name__ == "__main__":
    main()
