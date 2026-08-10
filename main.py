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
    PROMPT_HTML_PREFIX,
    PROMPT_HTML_SUFFIX,
    PROMPT_HTML_PLACEHOLDER,
)

_last_echoed_input: str = ""


def echo_user_input(text: str) -> None:
    # No-op: PromptSession already displays prompt and user input cleanly.
    pass


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
from ui.widgets.status_bar import AgentStatusBar
from ui.cc_style import status_compact_line
status_bar = AgentStatusBar()

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

    def _on_llm_started(p: dict) -> None:
        nonlocal _turn_index, _token_buf, _held_buf
        _token_buf = ""
        _held_buf = ""
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
        Console().print(status_compact_line(
            step=_turn_index, elapsed=p.get("duration") or _elapsed_for(_turn_index),
            thinking=True, tools=True, generating=True,
        ))
        renderer.flush()
        metrics.record_api_call(duration=p.get("duration", 1.0))

    def _on_tool_started(p: dict) -> None:
        if getattr(bus, "_on_tool_completed_active", False):
            return
        nonlocal _last_tool_args, _last_tool_name
        tool = p.get("tool") or p.get("name", "")
        args = p.get("args") or {}
        _last_tool_args = args
        _last_tool_name = tool
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


def _validate_fix_path(filepath: str) -> bool:
    """Return True if filepath is safe, False otherwise."""
    from core.kernel.security import get_workspace_root
    try:
        workspace_root = get_workspace_root()
        resolved_target = (workspace_root / filepath).resolve()
        resolved_target.relative_to(workspace_root)
        return True
    except (ValueError, OSError):
        return False

def _process_slash_command(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    if user_input.lower() in ("clear", "/clear", "/reset", "/c"):
        state.clear_context()
        state.set_messages([{"role": "system", "content": base_inst}])
        if hasattr(ctx.evidence_log, "clear"):
            ctx.evidence_log.clear()
        elif isinstance(ctx.evidence_log, list):
            ctx.evidence_log.clear()
        if hasattr(ctx.todo_manager, "clear"):
            ctx.todo_manager.clear()
        from core.accept_edits_state import reset_session
        reset_session()
        try:
            workspace_dir = get_workspace_root() if 'get_workspace_root' in globals() else Path.cwd()
            checkpoint_file = workspace_dir / CHECKPOINT_FILENAME
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                ctx.logger.info("Workspace checkpoint cleared.")
        except Exception as e:
            ctx.logger.warning(f"Failed to unlink checkpoint: {e}")
        sys.stdout.write("\n\033[92m✨ [System] Context and history have been cleared. Ready for a new task!\033[0m\n\n")
        sys.stdout.flush()
        return True

    if user_input.lower().startswith("/undo"):
        parts = user_input.split(maxsplit=1)
        undo_path = parts[1].strip() if len(parts) > 1 else ""
        if not undo_path:
            sys.stdout.write("\n\033[91m⚠ Usage: /undo <filepath>\033[0m\n\n")
        else:
            sys.stdout.write(f"\n{ctx.snapshot_engine.undo(undo_path)}\n\n")
        sys.stdout.flush()
        return True

    if user_input.strip() in ("فحص", "فحص مستودع", "scan", "scan repo", "/deep-scan"):
        from core.repo_scanner import SECURE_REPO_SCANNER
        try:
            from rich.console import Console
            from ui.widgets.scan_display import render_scan_result
            render_scan_result(
                Console(),
                SECURE_REPO_SCANNER()._deep_scan(get_workspace_root()),
            )
        except Exception as _scan_exc:
            sys.stdout.write(f"\n\033[91m⚠ deep scan failed: {_scan_exc}\033[0m\n\n")
        sys.stdout.flush()
        return True

    if user_input.lower().startswith(("/refactor", "nabd refactor", "/dag", "/resume", "nabd resume")):
        parts = user_input.split()
        is_resume = user_input.lower().startswith(("/resume", "nabd resume"))
        target_files_list = parts[1:] if len(parts) > 1 and not is_resume else ["target_dummy.py"]
        try:
            from llm_router import get_secure_model
            from tools.secure_tools import SecureGraphifyTool
            from core.dag.launcher import launch_nabdos_core
            from engine.consent import ConsentManager
            llm = get_secure_model()
            ws = str(get_workspace_root() if 'get_workspace_root' in globals() else Path.cwd())
            graphify = SecureGraphifyTool(workspace_dir=ws)
            taste_rules = ["All functions MUST have strict Type Hints.", "Use clear docstrings and comments."]
            # S-2-FINAL: توصيل الموافقة الفعلي — ConsentManager يُكيَّف إلى
            # ConsentCallback (confirm()→None = موافقة). كل أمر DAG طرفي
            # يُعرض على البشر قبل التنفيذ (أو يُسجَّل رفضًا عند غياب الإجابة).
            consent_manager = ConsentManager()
            consent_callback = lambda t, a: consent_manager.confirm(
                t, a, evidence_log=ctx.evidence_log, step=getattr(state, "step_count", 0)
            ) is None
            launch_nabdos_core(
                llm_engine=llm,
                graphify_tool=graphify,
                workspace_dir=ws,
                target_files=target_files_list,
                taste_rules=taste_rules,
                resume=is_resume,
                consent_callback=consent_callback,
            )
        except Exception as dag_err:
            sys.stdout.write(f"\n\033[91m❌ [DAG Launcher Error] {dag_err}\033[0m\n\n")
        sys.stdout.flush()
        return True

    if user_input.lower().startswith("/fix"):
        import ast as _ast
        import re as _re
        import subprocess as _sp

        remainder = user_input[len("/fix"):].strip()
        _m = _re.match(r'(.+?)\s*(?:->|→)\s*(.+)', remainder)
        if not _m:
            sys.stdout.write(
                "\n\033[91m⚠ Usage: /fix <filepath> → <function_name>\033[0m\n\n"
            )
            sys.stdout.flush()
            return True

        filepath = _m.group(1).strip()
        func_name = _m.group(2).strip()

        try:
            if not _validate_fix_path(filepath):
                sys.stdout.write("\n\033[91m⚠ Error: path outside workspace\033[0m\n\n")
                sys.stdout.flush()
                return

            target = Path(filepath)
            if not target.exists():
                sys.stdout.write(f"\n\033[91m⚠ File not found: {filepath}\033[0m\n\n")
                sys.stdout.flush()
                return True

            content = target.read_text(encoding="utf-8")
            tree = _ast.parse(content, filename=filepath)

            # Find function — walk top-level and class methods
            found = None
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == func_name:
                    found = node
                    break

            if not found:
                sys.stdout.write(
                    f"\n\033[91m⚠ Function '{func_name}' not found in {filepath}\033[0m\n\n"
                )
                sys.stdout.flush()
                return True

            lines = content.splitlines()
            start = found.lineno - 1
            end = getattr(found, "end_lineno", len(lines))
            func_lines = lines[start:end]

            # 1. Display the function with line numbers
            sys.stdout.write(
                f"\n\033[94m📄 {filepath} — function: {func_name}"
                f" (L{found.lineno}-{end})\033[0m\n"
            )
            sys.stdout.write(f"\033[90m{'─' * 60}\033[0m\n")
            for i, line in enumerate(func_lines, start=found.lineno):
                sys.stdout.write(f"\033[2m{i:4d}│\033[0m {line}\n")
            sys.stdout.write(f"\033[90m{'─' * 60}\033[0m\n")
            sys.stdout.flush()

            # 2. Run tests
            sys.stdout.write("\n\033[94m🧪 Running ui tests...\033[0m\n")
            sys.stdout.flush()
            result = _sp.run(
                ["python3", "-m", "pytest", "tests/", "-k", "ui", "-v"],
                cwd=str(Path.cwd()),
                capture_output=True, text=True, timeout=60,
            )
            sys.stdout.write(result.stdout + "\n")
            if result.stderr:
                sys.stdout.write(f"\033[91m{result.stderr}\033[0m\n")
            if result.returncode == 0:
                sys.stdout.write("\033[92m✅ All tests passed!\033[0m\n\n")
            else:
                sys.stdout.write(
                    f"\033[91m❌ Tests failed (exit code {result.returncode})"
                    " — fix the function above, then re-run /fix\033[0m\n\n"
                )
            sys.stdout.flush()

        except SyntaxError as exc:
            sys.stdout.write(f"\n\033[91m⚠ Syntax error in {filepath}: {exc}\033[0m\n\n")
            sys.stdout.flush()
        except _sp.TimeoutExpired:
            sys.stdout.write("\n\033[91m⚠ Tests timed out after 60s\033[0m\n\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(f"\n\033[91m⚠ Error: {exc}\033[0m\n\n")
            sys.stdout.flush()

        return True

    if user_input.lower().startswith("/expand"):
        # UI-CC-3: expand a previously collapsed output block by id.
        parts = user_input.split(maxsplit=1)
        cid_arg = parts[1].strip() if len(parts) > 1 else ""
        from ui.cc_style import CollapseStore, collapse_store
        if not cid_arg:
            ids = collapse_store.ids()
            if not ids:
                sys.stdout.write("\n\033[2m(no collapsed blocks to expand)\033[0m\n\n")
            else:
                sys.stdout.write(f"\n\033[2mCollapsed blocks: {', '.join(str(i) for i in ids)} — /expand <id>\033[0m\n\n")
            sys.stdout.flush()
            return True
        try:
            cid = int(cid_arg)
        except ValueError:
            sys.stdout.write(f"\n\033[91m⚠ /expand expects a numeric id, got '{cid_arg}'\033[0m\n\n")
            sys.stdout.flush()
            return True
        block = collapse_store.expand(cid)
        if block is None:
            sys.stdout.write(f"\n\033[91m⚠ No collapsed block with id {cid}\033[0m\n\n")
            sys.stdout.flush()
            return True
        sys.stdout.write(f"\n{'─' * 40}\n")
        for line in block:
            sys.stdout.write(f"  {line}\n")
        sys.stdout.flush()
        return True

    return False


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

    base_inst = (
        "You are an advanced Autonomous Agent running on a Linux environment.\n"
        "CRITICAL RULE: Respond ONLY in English.\n"
        "\n"
        "=== TASK CLASSIFICATION - APPLY THIS FIRST ===\n"
        "A) GENERAL / GREETINGS / MATH / FACTS / COUNTRIES (e.g. 'hi', 'hello', 'iraq', '1+1', 'what is Iraq?'):\n"
        " - Answer DIRECTLY from your own knowledge.\n"
        " - DO NOT call file_system, web_search, search_memory, todo_write, execute_shell, or ANY tool.\n"
        " - NEVER say 'I don\\'t have information' or 'I don\\'t have sufficient evidence' for this category.\n"
        " - Examples: 'hi' -> 'Hello! How can I help?'; 'iraq' -> 2-3 sentences about Iraq; '1+1' -> '2'.\n"
        "\n"
        "B) CODEBASE / FILESYSTEM / PROJECT TASKS:\n"
        " - You MUST use the appropriate tool.\n"
        " - Every factual statement about codebase/filesystem must be backed by tool output or verified memory.\n"
        " - Never invent file names, architectures, or statistics.\n"
        " - WORKSPACE ROOT: Your current working directory IS the repository root. Use relative paths.\n"
        "\n"
        "D) LANGUAGE & ACCURACY (CRITICAL):\n"
        " - ALWAYS respond in the SAME LANGUAGE as the user's query.\n"
        " - If the user writes in Arabic, respond fully in Arabic.\n"
        " - Never fabricate: if unknown, say 'لا أعرف'.\n"
        " - Spell technical terms correctly (Python, not Pathon).\n"
        "\n"
        "BEHAVIOR:\n"
        "- Max 2 thoughts before action.\n"
        "- For complex calculations you MAY use execute_shell python3 -c \"print(...)\" but simple math answer directly.\n"
        "\n"
        "C) AFTER SHELL EXECUTION (CRITICAL):\n"
        " - You ALREADY HAVE the command output from execute_shell.\n"
        " - DO NOT call file_system.read to read files individually after execute_shell.\n"
        " - Summarize the Shell output directly in your final_answer.\n"
        " - Example: If 'ls' shows 12 files, say 'The directory contains 12 files: file1, file2, ...'\n"
        " - NEVER call file_system.read after execute_shell unless explicitly asked.\n"
        + TODO_DISCIPLINE
    )
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
    from prompt_toolkit.formatted_text import ANSI, HTML
    from prompt_toolkit.key_binding import KeyBindings

    plan_mode: bool = False

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
                    HTML(
                        f"{PROMPT_HTML_PREFIX}\n{PROMPT_HTML_SUFFIX}"
                    ),
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
