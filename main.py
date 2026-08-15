"""main.py — NABD Agent OS TUI entry point.

Single-renderer architecture: Renderer owns stdout, PromptSession owns input.

STRUCTURE (CC reduction — Phase 6.2):
  _build_app()       → AppContext + wire_events + session restore + shutdown
  _run_repl()        → REPL setup + one-shot query + interactive loop
  main()             → CLI flags + SIGINT + dispatch to _build_app → _run_repl
  _process_slash_command()  → standalone slash-command handler (unchanged)
"""

from __future__ import annotations

import time
import json
import os
import html
import sys
import threading
from typing import Any
from pathlib import Path
from core.utils import safe_strip
from core.kernel.security import get_workspace_root
from engine.deep_agent import CHECKPOINT_FILENAME
from core.turn_outcome import TurnOutcome, TurnStatus
from core.text_utils import safe_display
from ui.design.theme.semantic import SEMANTIC
from ui.theme import (
    PROMPT_HTML_SUFFIX,
    PROMPT_HTML_PLACEHOLDER,
)
from engine.ui_theme import workflow_prompt_hint
from core.prompts import BASE_INSTRUCTIONS
base_inst = BASE_INSTRUCTIONS


_last_echoed_input: str = ""


def echo_user_input(text: str) -> None:
    # No-op: PromptSession already displays prompt and user input cleanly.
    pass


def toggle_workflow_mode_from_shortcut(state: Any) -> str:
    """Toggle normal/PLAN from Shift+Tab without revoking approved APPLY mode."""
    from core.plan_apply import (
        APPLY_MODE,
        PLAN_MODE,
        PLAN_MODE_INSTRUCTION,
        current_mode,
        enter_plan_mode,
        return_to_normal_mode,
        synchronize_mode_context,
    )

    mode = current_mode(state)
    if mode == APPLY_MODE:
        return mode
    if mode == PLAN_MODE:
        return_to_normal_mode(state)
        synchronize_mode_context(state, None)
    else:
        enter_plan_mode(state)
        synchronize_mode_context(state, PLAN_MODE_INSTRUCTION)
    return current_mode(state)


# ── Tool output summariser ─────────────────────────────────────────────────

from core._exact_action_contract import EXACT_ACTION_PATTERNS


def _summarise_tool(tool: str, args: dict, result) -> tuple[str, str, str]:
    """Return (badge, message, color) for a completed tool call.

    Used only as fallback; UI theme methods (tool_start/tool_end) are
    the primary rendering path.

    Phase 2.E: For shell commands, render the actual bounded stdout for
    short outputs (<= 5 lines). Longer outputs keep compact line-count
    summary. Failed commands always show error snippet.
    """
    if tool == "execute_shell":
        cmd = (args.get("command") or "")[:60]
        out = safe_strip(getattr(result, "stdout", ""))
        err = safe_strip(getattr(result, "stderr", ""))
        if getattr(result, "success", False):
            lines = len(out.splitlines()) if out else 0
            if lines > 0 and lines <= 5 and out:
                # Short output: show actual content (bounded to 300 chars)
                display = out[:300].strip()
                if len(out) > 300:
                    display += "..."
                return ("EXEC", f"{cmd}\n{display}", "cyan")
            return ("EXEC", f"{cmd} ({lines} lines)", "cyan")
        else:
            snippet = (err or out).splitlines()[0][:80] if (err or out) else "unknown error"
            return ("ERROR", snippet, "red")

    if tool == "file_system":
        action = str(args.get("action", "")).lower()
        path = str(args.get("path", ""))
        if getattr(result, "success", False):
            if action in ("read", "list"):
                out = safe_strip(getattr(result, "stdout", ""))
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
            out = safe_strip(getattr(result, "stdout", ""))
            count = out.count("[")
            return ("SEARCH", f'"{query}" ({count} results)', "cyan")
        return ("SEARCH", f'"{query}" — failed', "red")

    if tool == "search_memory":
        query = str(args.get("query", ""))[:40]
        if getattr(result, "success", False):
            out = safe_strip(getattr(result, "stdout", ""))
            count = out.count("[") if "[" in out else (1 if out else 0)
            return ("MEMORY", f'"{query}" ({count} hits)', "cyan")
        return ("MEMORY", f'"{query}" — failed', "red")

    return ("TOOL", tool, "cyan")


def _extract_final_answer_text(raw: Any) -> str:
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
    if not raw or not safe_strip(raw):
        return raw if isinstance(raw, str) else (str(raw) if raw is not None else "")
    if not isinstance(raw, (str, bytes, bytearray)):
        return str(raw)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return raw if isinstance(raw, str) else str(raw)
    if not isinstance(payload, dict):
        return raw if isinstance(raw, str) else str(raw)
    if payload.get("tool") != "final_answer":
        return raw if isinstance(raw, str) else str(raw)
    args = payload.get("args")
    if not isinstance(args, dict):
        return raw if isinstance(raw, str) else str(raw)
    answer = args.get("answer")
    if not isinstance(answer, str):
        return raw if isinstance(raw, str) else str(raw)
    return answer


# ── Event Wiring ───────────────────────────────────────────────────────────
from ui.event_wiring import (wire_events, _mark_step, _elapsed_for)  # ARCH-5
from ui.widgets.status_bar import AgentStatusBar
status_bar = AgentStatusBar()

# ── System Setup ───────────────────────────────────────────────────────────

# setup_system migrated to core/app_context.py: AppContext.build()


# ── CLI flag check ─────────────────────────────────────────────────────────

def _check_cli_flags() -> bool:
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
            "  -h, --help              Show this help message and exit\n"
            "  -v, --version           Show program version and exit\n"
            "  --auto-discover         Auto-discover new tools in tools/ (default)\n"
            "  --no-auto-discover      Disable tool auto-discovery\n"
        )
        sys.exit(0)
    return False


# ── Helper: cleanup after streamed failure ─────────────────────────────────

def _cleanup_after_streamed_failure(state: Any, ctx: Any, exc: Any) -> None:
    """After streaming output, the verifier rejected the answer."""
    msgs = state.get_messages()
    if msgs and msgs[-1].get("role") == "assistant":
        state.set_messages(msgs[:-1])
    ctx.logger.error(f"ToolRequiredError: {exc}")
    ctx.renderer.think_end()
    ctx.renderer.verifier_reject(str(exc))
    ctx.renderer.flush()


# ── One-shot query handler ─────────────────────────────────────────────────

def _handle_one_shot_query(
    positional_queries: list[str],
    state: Any,
    ctx: Any,
    visualizer: Any,
    ExecutionLoop: Any,
    ToolRequiredError: Any,
) -> None:
    one_shot_query = " ".join(positional_queries)
    state.reset_step_count()

    # ── Phase 2.C: Exact-action mode detection ──
    _exact_action_mode = any(p in one_shot_query.lower() for p in EXACT_ACTION_PATTERNS)
    if _exact_action_mode:
        _exact_inst = (
            "[EXACT ACTION CONSTRAINT] The user specified exactly one shell command. "
            "You MUST use execute_shell only. Do NOT call any other tool. "
            "Execute the single command and return its output."
        )
        if hasattr(state, "append_message"):
            state.append_message({"role": "system", "content": _exact_inst})

    engine = ExecutionLoop(
        state=state,
        max_output_len=ctx.config.max_output,
        evidence_log=ctx.evidence_log,
        todo_manager=ctx.todo_manager,
        logger=ctx.logger,
        no_stream=os.getenv("NABD_NO_STREAM", "").lower() in ("1", "true", "yes"),
        exact_action_mode=_exact_action_mode,
    )
    try:
        # S-1: Validate /fix path traversal
        if one_shot_query.startswith('/fix'):
            import re
            m = re.match(r'/fix\s+(.+?)\s*(?:->|→)\s*(.+)', one_shot_query)
            if m:
                filepath = m.group(1).strip()
                if not _validate_fix_path(filepath):
                    sys.stdout.write("\n\033[91m⚠ Error: path outside workspace\033[0m\n\n")
                    sys.stdout.flush()
                    sys.exit(1)  # إنهاء فوري لمنع السقوط في REPL loop

        outcome = engine.run(one_shot_query)
        display_text = outcome.safe_message or outcome.final_answer or "(Session completed - no text returned)"
        if sys.stdout.isatty():
            from rich.console import Console
            import ui.cc_style as cc_style
            Console().print(cc_style.render_final_answer(display_text))
        else:
            ctx.renderer.stream_chunk(display_text)
        ctx.renderer.flush()
    except ToolRequiredError as exc:
        _cleanup_after_streamed_failure(state, ctx, exc)
    except KeyboardInterrupt:
        ctx.renderer.think_end()
        sys.stdout.write("\n[bold yellow]⚠ Execution interrupted by user.[/bold yellow]\n")
        sys.stdout.flush()
    except Exception as exc:
        ctx.renderer.stream_chunk(str(exc))
        ctx.renderer.flush()
        ctx.logger.error(f"Execution failed: {exc}")
    finally:
        ctx.session_manager.messages = state.get_messages()
        ctx.session_manager.todos = ctx.todo_manager.to_serializable()
        ctx.session_manager.evidence = ctx.evidence_log.to_serializable().get("records", [])
        ctx.session_manager.save()
        visualizer.stop()
    sys.exit(0)


# ── Slash-command handler ──────────────────────────────────────────────────


from core.command_dispatcher import (process_slash_command as _process_slash_command, validate_fix_path as _validate_fix_path)  # ARCH-6

# ── Interactive turn handler ───────────────────────────────────────────────

def _run_interactive_turn(
    user_input: str,
    state: Any,
    ctx: Any,
    visualizer: Any,
    ExecutionLoop: Any,
    ToolRequiredError: Any,
) -> None:
    from core.sanitize import sanitize
    from core.parser import normalize
    import termios

    clean_prompt = normalize(user_input)[:10000]

    # ── Phase 2.D: TODO isolation — scope TODOs on new unrelated task ──
    # A new user request that does NOT explicitly reference or continue the
    # prior task starts a new scope (old TODOs preserved but inactive).
    # Only explicit continuation signals (user says "continue", "resume")
    # restore the previous scope. Per protocol 2.D: "Do NOT invent additional
    # heuristics beyond this explicit-signal rule."
    # Old TODOs are NEVER deleted — only scoped out.
    _user_input_lower = user_input.lower().strip()
    _is_continuation = _user_input_lower.startswith(("continue", "resume")) or \
        any(_user_input_lower.startswith(s) for s in ("continue ", "resume ",
            "continue:", "resume:", "continue the", "resume the",
            "continue my", "resume my", "continue prior", "resume prior"))
    if _is_continuation:
        # Explicit continuation: restore previous scope if available.
        if hasattr(ctx.todo_manager, "pop_scope"):
            ctx.todo_manager.pop_scope()
    else:
        # New unrelated task: push current scope (preserve old TODOs).
        if hasattr(ctx.todo_manager, "push_scope"):
            _task_id = f"task_{_user_input_lower[:20]}"
            ctx.todo_manager.push_scope(_task_id)

    # ── Phase 2.C: Exact-action contract enforcement ──────────────────────
    # Phase 2.C: detect exact-action mode for engine-level enforcement.
    _exact_action_mode = False
    if any(p in user_input.lower() for p in EXACT_ACTION_PATTERNS):
        _exact_action_mode = True
        _exact_inst = (
            "[EXACT ACTION CONSTRAINT] The user specified exactly one shell command. "
            "You MUST use execute_shell only. Do NOT call file_system, web_search, "
            "or any other tool. Execute the single command and return its output."
        )
        if hasattr(state, "append_message"):
            state.append_message({"role": "system", "content": _exact_inst})

    # ── Stage 3: Temporal / current-information intent detection ────────────
    # If the user asks for "latest", "today", "news", or similar time-bound
    # info, inject a system message that forces web_search instead of relying
    # on the LLM's static training-data memory.
    from core.temporal_intent import detect_temporal_intent, build_temporal_system_message
    _intent = detect_temporal_intent(user_input)
    if _intent is not None and hasattr(state, "append_message"):
        _search_available = (
            ctx.tool_registry is not None
            and "web_search" in ctx.tool_registry
        )
        _temporal_msg = build_temporal_system_message(
            _intent, has_search_tool=_search_available
        )
        state.append_message({"role": "system", "content": _temporal_msg})

    if hasattr(visualizer, "_final_answer_rendered"):
        visualizer._final_answer_rendered = False

    state.reset_step_count()
    engine = ExecutionLoop(
        state=state,
        max_output_len=ctx.config.max_output,
        evidence_log=ctx.evidence_log,
        todo_manager=ctx.todo_manager,
        logger=ctx.logger,
        no_stream=os.getenv("NABD_NO_STREAM", "").lower() in ("1", "true", "yes"),
        exact_action_mode=_exact_action_mode,
    )

    fd = sys.stdin.fileno()
    old_termios = None
    try:
        old_termios = termios.tcgetattr(fd)
        new = list(old_termios)
        new[3] = new[3] & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, new)

        outcome = engine.run(clean_prompt)
        display_text = outcome.safe_message or outcome.final_answer or "(Session completed - no text returned)"
        visualizer._on_loop_completed({"response": display_text})

    except KeyboardInterrupt:
        ctx.renderer.think_end()
        visualizer.console.print("\n[bold yellow]⚠ Execution interrupted by user.[/bold yellow]")
    except ToolRequiredError as exc:
        _cleanup_after_streamed_failure(state, ctx, exc)
    except Exception as exc:
        visualizer._on_loop_completed({"response": exc})
        ctx.logger.error(f"Execution failed: {exc}")
    finally:
        if old_termios is not None:
            termios.tcsetattr(fd, termios.TCSANOW, old_termios)
        try:
            termios.tcflush(fd, termios.TCIFLUSH)
        except Exception:
            pass

    ctx.session_manager.messages = state.get_messages()
    ctx.session_manager.todos = ctx.todo_manager.to_serializable()
    ctx.session_manager.evidence = ctx.evidence_log.to_serializable().get("records", [])
    ctx.session_manager.save()


# =========================================================================
# _build_app — assemble all dependencies once
# =========================================================================

def _build_app() -> tuple:
    """Build AppContext, RuntimeState, visualizer, and system prompt.

    Returns: (ctx, state, visualizer, base_inst, ExecutionLoop, ToolRequiredError)
    """
    import signal
    from core.cancellation import CancelToken
    from core.kernel.state import RuntimeState
    from engine.loop import ExecutionLoop, ToolRequiredError
    from core.kernel.events import bus
    from ui.repl_termux import TerminalVisualizer
    from core.app_context import AppContext
    from core.constants import TODO_DISCIPLINE

    # One-time splash
    try:
        import nabd_logo  # type: ignore[import-untyped]
        nabd_logo.draw()
    except Exception:
        pass

    ctx = AppContext.build()
    state = RuntimeState(session_id=ctx.session_manager.session_id, max_steps=50)
    ctx.session_manager.enforce_retention_policy(ctx.config.max_sessions)

    # Restore todos + evidence from latest session (v2+ only)
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

    # Construct visualizer WITHOUT event listeners for single-renderer mode
    visualizer = TerminalVisualizer(event_bus=bus, state=state, register_listeners=False)

    # Isolate provider state file per session
    from llm_router import router as _provider_router
    _provider_router.set_state_key(ctx.session_manager.session_id[:12])

    # Graceful shutdown handler
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

    # D1 FIX: single RuntimeState — no second construction.
    # The state created at line 670 is the ONLY instance. It carries
    # the session restore data and is shared by visualizer, loop,
    # dispatcher, and the shutdown handler.

    state.append_message({"role": "system", "content": base_inst})

    return ctx, state, visualizer, base_inst, ExecutionLoop, ToolRequiredError


# =========================================================================
# _run_repl — interactive prompt loop
# =========================================================================

def _ansi_fg(rgb: tuple, text: str) -> str:
    """Wrap text in a 24-bit foreground ANSI escape from an (r,g,b) tuple."""
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\033[0m"


def _run_repl(
    ctx: Any,
    state: Any,
    visualizer: Any,
    base_inst: str,
    ExecutionLoop: Any,
    ToolRequiredError: Any,
) -> None:
    """Run the REPL: accepts input, dispatches to slash handler or agent."""
    import sys
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings

    from core.plan_apply import APPLY_MODE, PLAN_MODE, current_mode, task_graph_live_status

    def _prompt_chrome() -> HTML:
        mode = current_mode(state)
        task_summary = task_graph_live_status(state) or ""
        hint = workflow_prompt_hint(mode, task_summary)
        hint_html = html.escape(hint).replace("\n", "<br/>")
        color = "ansigreen" if mode == APPLY_MODE else ("ansiyellow" if mode == PLAN_MODE else "ansimagenta")
        rule = "─" * 48

        # Stage 3 (UI plan): a compact context bar above the prompt with
        # workspace root + mode + graph status — from real state only.
        # Stage 4 (privacy): show the project NAME (or short form), never the
        # full absolute workspace path, unless an explicit diagnostic flag is
        # set (e.g. NABD_DIAGNOSTIC_PATHS=1).
        from core.kernel.security import is_workspace_pinned, display_path
        if is_workspace_pinned():
            _diag = os.getenv("NABD_DIAGNOSTIC_PATHS", "").lower() in ("1", "true", "yes")
            ws_label = display_path(get_workspace_root(), diagnostic=_diag)
            if len(ws_label) > 48:
                ws_label = ws_label[:45] + "..."
        else:
            ws_label = "no workspace selected"
        ws_html = html.escape(ws_label)
        mode_label = "normal" if mode not in (APPLY_MODE, PLAN_MODE) else mode
        graph_part = ""
        if task_summary:
            # task_summary already contains "TaskGraph rX ..." — show only
            # the mode + ready/active portion to keep the line compact.
            graph_part = f"  ·  {html.escape(task_summary)}"
        ctx_line = (
            f"<style fg='grey'>workspace: {ws_html}  ·  mode: {mode_label}</style>"
            f"<style fg='grey'>{graph_part}</style>"
        )

        return HTML(
            f"<style fg='grey'>{rule}</style><br/>"
            f"{ctx_line}<br/>"
            f"<style fg='{color}'>{hint_html}</style><br/>"
            f"{PROMPT_HTML_SUFFIX}"
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
        """Toggle the real read-only PLAN mode; never revoke an approved APPLY by keypress."""
        toggle_workflow_mode_from_shortcut(state)

    input_session = PromptSession(
        history=InMemoryHistory(),
        mouse_support=False,
        # Single-line mode: 'Enter' submits immediately even with pasted newlines.
        multiline=False,
        key_bindings=bindings,
    )

    # Flush setup output before first prompt
    ctx.renderer.flush()

    # Check for CLI one-shot query
    positional_queries = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if positional_queries:
        _handle_one_shot_query(
            positional_queries, state, ctx, visualizer, ExecutionLoop, ToolRequiredError
        )
        return

    try:
        while True:
            try:
                user_input = input_session.prompt(
                    _prompt_chrome(),
                    placeholder=HTML(PROMPT_HTML_PLACEHOLDER),
                ).strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break
            if _process_slash_command(user_input, state, ctx, base_inst):
                continue

            _run_interactive_turn(
                user_input, state, ctx, visualizer, ExecutionLoop, ToolRequiredError
            )
    finally:
        visualizer.stop()


# =========================================================================
# main — entry point (CC ≤ 8)
# =========================================================================

def main() -> None:
    """NABD Agent OS entry point — CLI flags, SIGINT, then dispatch."""
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

    # A.2: Termux Environment Guard (Replaces taste.md prompt rule)
    if "com.termux" not in os.environ.get("PREFIX", ""):
        from rich.console import Console
        from rich.panel import Panel
        Console().print(
            Panel(
                "[bold red]❌ SECURITY VIOLATION: NABD OS requires a Termux environment (PREFIX).[/]",
                border_style="red"
            )
        )
        sys.exit(1)

    if _check_cli_flags():
        return

    import signal
    from core.cancellation import CancelToken

    ctx, state, visualizer, base_inst, ExecutionLoop, ToolRequiredError = _build_app()

    def _handle_sigint(sig, frame):
        """Emergency stop: save session and exit cleanly.

        On first Ctrl+C during generation, cancel the stream. On second
        Ctrl+C (or Ctrl+C outside generation), perform a full emergency
        shutdown: persist session state and exit with code 0.
        """
        from rich.console import Console
        from rich.panel import Panel

        if CancelToken().is_cancelled:
            # Second Ctrl+C: emergency stop
            Console().print(
                Panel(
                    "[bold red]🛑 إيقاف طارئ — جاري إنهاء الجلسة...[/]",
                    border_style="red",
                )
            )
            try:
                ctx.session_manager.messages = state.get_messages()
                ctx.session_manager.todos = ctx.todo_manager.to_serializable()
                ctx.session_manager.evidence = ctx.evidence_log.to_serializable().get("records", [])
                ctx.session_manager.save()
                ctx.memory_manager.close()
            except Exception:
                pass
            sys.exit(0)
        else:
            # First Ctrl+C: cancel the stream
            CancelToken().cancel("user (Ctrl+C)")

    signal.signal(signal.SIGINT, _handle_sigint)

    _run_repl(ctx, state, visualizer, base_inst, ExecutionLoop, ToolRequiredError)


if __name__ == "__main__":
    main()
