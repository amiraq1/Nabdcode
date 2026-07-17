# ui/repl_termux.py
"""
Sequential Cyberpunk REPL Mode for Termux (prompt_toolkit + Rich).
100% native Android Soft Keyboard, Copy/Paste, and Readline History support.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import SPINNERS
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from core.ui_bridge import get_bridge
from core.context_manager import RepositoryContextManager
from core.permissions import ShellPermissions, PermissionEngine
from core.kernel.state import RuntimeState
from ui.live_thought import LiveThoughtCompressor, render_bento_badge
from core.utils import safe_strip
from ui.theme import nabd_theme, BOX_THOUGHT, BOX_EXECUTION, BOX_EVIDENCE, BOX_FINAL

console = Console(theme=nabd_theme)


# Single source of truth for the always-on TODO view.
#
# DESIGN NOTE (unification): previously this REPL re-parsed the persisted
# STATE.md file via render_todo_block() on every prompt, producing a SECOND
# TODO box stacked under the bus-driven `show_todo_list` checklist. That
# duplicated the task list on screen and violated the deep_agent.py design
# decision that there must NOT be two parallel task lists on screen.
#
# The authoritative plan now lives in the TodoManager, which pushes changes to
# the UI bridge via on_plan_updated(). We render that single stream — not
# a second STATE.md parser. RepositoryContextManager STILL writes STATE.md
# (LMK-resume safe); we only stop *rendering* it twice.
_todo_plan_cache: list[dict] = []


def _render_todo_from_plan(plan: list[dict]) -> None:
    """Render the live TODOS box from the bus-driven plan (single source).

    Always-on: shows the current plan even when the agent is idle, but reads
    it from the SAME TodoManager stream the checklist uses — no second parser,
    no duplicate box. Renders nothing on empty/parse failure (fail-safe).
    """
    global _todo_plan_cache
    if plan:
        _todo_plan_cache = list(plan)
    items = _todo_plan_cache
    if not items:
        return
    try:
        in_progress = [i for i in items if str(i.get("status", "")).lower() == "in_progress"]
        completed = [i for i in items if str(i.get("status", "")).lower() == "done"]
    except Exception:
        return

    total = len(in_progress) + len(completed)
    print(f"\n\033[45;37m TODOS \033[0m [\033[36m{total} items\033[0m]")
    for task in in_progress:
        print(f"\033[32m ☐ {task.get('content', task.get('text', ''))}\033[0m")
    for task in completed:
        print(f"\033[32;9m ☑ {task.get('content', task.get('text', ''))}\033[0m")


def render_todo_block(plan: list[dict] | None = None) -> None:
    """Render the live TODOS box (single source: the TodoManager plan).

    Kept as a thin wrapper so existing call sites keep working. The STATE.md
    file-read duplicate has been removed — see module-level DESIGN NOTE.
    """
    _render_todo_from_plan(plan or [])

# Module-level thought compressor, shared between the async event consumer
# and the REPL key-binding handler (Ctrl+O expand).
# Module-level session permission state. Transient: reset on each fresh REPL
# boot (a hard restart), matching the constraint that rules must not survive
# restarts. When the agent exposes a RuntimeState, its own shell_permissions
# take precedence so policy follows the live execution loop.
_SESSION_PERMS_STATE: RuntimeState = RuntimeState(session_id="repl-perms")
_SESSION_PERMS: ShellPermissions = _SESSION_PERMS_STATE.shell_permissions


def _resolve_runtime_state(agent) -> RuntimeState:
    """Best-effort resolve the RuntimeState driving the current agent.

    Prefers the agent's own state (ExecutionLoop.state / NativeDeepAgent.
    runtime_state) so the PermissionEngine reads the exact object the shell
    gate consults. Falls back to the module-level session state otherwise.
    """
    if agent is not None:
        state = getattr(agent, "state", None) or getattr(agent, "runtime_state", None)
        if isinstance(state, RuntimeState):
            return state
    return _SESSION_PERMS_STATE


def _erase_live_line() -> None:
    """Cleanly clear the single live status row before a full-width print.

    The Kinetic status line (and the LiveThought compressor) own one terminal
    row written via raw ``sys.stdout``. A ``console.print`` of a Rich
    Panel for a config command (/goal, /skill, /allow) lands on the
    scrollback *under* that live row and can momentarily collide with
    it. Erasing the row first (``\\r\\033[K``) lets the panel print
    onto a clean line; the Kinetic spinner thread redraws its own row
    on the next 100ms tick, so there is no deadlock and no shared-lock
    contention — both writers use the same primitive stdout write.
    """
    try:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
    except Exception:
        pass


def _handle_permission_command(text: str, agent=None) -> bool:
    """Handle /allow /deny /clear_perms slash commands.

    Returns True if the text was a permission command (and thus consumed; the
    agent should NOT be invoked for it). Emits quiet, non-flickering console
    feedback. Never prompts interactively; never weakens the Phase 2.1
    heuristics (the PermissionEngine runs those first regardless).
    """
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    perms = _resolve_runtime_state(agent).shell_permissions

    if cmd == "/allow":
        pattern = parts[1].strip() if len(parts) > 1 else ""
        if not pattern:
            _erase_live_line()
            console.print("[#ff5555]Usage: /allow <pattern>  (e.g. /allow git *, /allow ls -la)[/#]")
            return True
        perms.add_allow(pattern)
        _erase_live_line()
        console.print(f"[#55ff55]✓ Permission added: ALLOW [{pattern}][/#]")
        return True
    if cmd == "/deny":
        pattern = parts[1].strip() if len(parts) > 1 else ""
        if not pattern:
            _erase_live_line()
            console.print("[#ff5555]Usage: /deny <pattern>  (e.g. /deny rm *, /deny curl *)[/#]")
            return True
        perms.add_deny(pattern)
        _erase_live_line()
        console.print(f"[#ffaa55]⛔ Permission added: DENY [{pattern}][/#]")
        return True
    if cmd == "/clear_perms":
        perms.clear()
        _erase_live_line()
        console.print("[#aaaaaa]Permission ruleset cleared (back to interactive ask).[/#]")
        return True
    return False


def _handle_goal_command(text: str, agent=None) -> Any:
    """Handle the /goal <desc> [|| <criteria>] command with rich panel feedback."""
    from core.kernel.state import parse_goal_command

    spec = parse_goal_command(text)
    if spec is None:
        return None

    state = _resolve_runtime_state(agent)
    state.active_goal = spec

    try:
        from core.ui_bridge import get_bridge
        bridge = get_bridge()
        bridge.emit("goal_set", goal_desc=spec.raw_prompt)
    except Exception:
        pass

    _erase_live_line()
    panel_content = Text()
    panel_content.append("🎯 Objective: ", style="bold cyan")
    panel_content.append(spec.raw_prompt + "\n\n")

    if spec.success_criteria:
        panel_content.append("✅ Criteria (done_when):\n", style="bold yellow")
        panel_content.append(spec.success_criteria)
    else:
        panel_content.append("⚠️  No explicit criteria. Agent will determine success.", style="dim")

    panel_content.append("\n\n")
    panel_content.append("The agent won't report Success until criteria are proven.", style="italic dim")

    console.print(Panel(panel_content, title="[bento.execution.title] 🎯 Goal Active [/bento.execution.title]", border_style="bento.execution.border", box=BOX_EXECUTION, padding=(1, 2)))
    return f"Goal set: {spec.raw_prompt}"


class REPL:
    """REPL interface wrapper supporting object-oriented handlers and bridge events."""
    def __init__(self, bridge: Any = None, loop: Any = None):
        self._bridge = bridge
        self._loop = loop

    def _handle_goal_command(self, cmd: str) -> Optional[str]:
        """Enhanced goal command with rich panel feedback"""
        from core.kernel.state import parse_goal_command
        goal = parse_goal_command(cmd)
        if not goal:
            return None

        if self._loop and hasattr(self._loop, "state") and self._loop.state:
            self._loop.state.active_goal = goal

        if self._bridge and hasattr(self._bridge, "emit"):
            self._bridge.emit("goal_set", goal_desc=goal.raw_prompt)

        panel_content = Text()
        panel_content.append("🎯 Objective: ", style="bold cyan")
        panel_content.append(goal.raw_prompt + "\n\n")

        if goal.success_criteria:
            panel_content.append("✅ Criteria (done_when):\n", style="bold yellow")
            panel_content.append(goal.success_criteria)
        else:
            panel_content.append("⚠️  No explicit criteria. Agent will determine success.", style="dim")

        panel_content.append("\n\n")
        panel_content.append("The agent won't report Success until criteria are proven.", style="italic dim")

        console.print(Panel(panel_content, title="[bento.execution.title] 🎯 Goal Active [/bento.execution.title]", border_style="bento.execution.border", box=BOX_EXECUTION, padding=(1, 2)))
        return f"Goal set: {goal.raw_prompt}"

    def _render_prompt_with_goal(self) -> str:
        """Enhanced prompt showing active goal status"""
        if not self._loop or not hasattr(self._loop, "state") or not self._loop.state:
            return "❯ "
        goal = self._loop.state.active_goal
        if goal and not goal.is_met:
            return f"❯ [Goal: {goal.raw_prompt[:20]}...] "
        return "❯ "


def _resolve_evidence_log(agent) -> Any:
    """Best-effort resolve the live EvidenceLog driving the agent (or None)."""
    if agent is not None:
        log = getattr(agent, "evidence_log", None)
        if log is not None:
            return log
    return None


def _handle_skill_command(text: str, agent=None) -> bool:
    """Handle the ``/skill <name>`` command (Phase 6 Native Skills Loader).

    Returns True if the text was a skill command (and thus consumed). The skill
    command is executed through ``core.skills.execute_skill``, which:

      a) merges the skill's ``allowed_tools`` into the live RuntimeState
         shell_permissions as explicit ALLOW rules (consulted by the
         PermissionEngine for this session);
      b) dispatches the skill ``command`` via ``ShellTool.execute()`` — the SAME
         code path the agent uses — so the non-overridable Phase 2.1 heuristics
         (base64/hex/eval blocks, obfuscation sweep) still run first, and a
         ``ToolResult`` is produced;
      c) appends that result to the evidence ledger when one is available.

    Fail-silent: an unknown skill name or a discovery miss prints a quiet error
    and consumes the input (the command is never forwarded to the agent as a
    task). A blocked/safe-rejected command still prints the ToolResult so the
    operator sees the security outcome.
    """
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    if cmd != "/skill":
        return False

    # Split the skill name from any trailing arguments (e.g. a target file for
    # parameterized skills like ``/skill reviewer core/state.py``).
    name_arg = parts[1].strip() if len(parts) > 1 else ""
    if not name_arg:
        _erase_live_line()
        console.print("[#ff5555]Usage: /skill <name> [args...]  (list skills with /skills)[/#]")
        return True
    _name_parts = name_arg.split(maxsplit=1)
    name = _name_parts[0]
    skill_args = _name_parts[1].strip() if len(_name_parts) > 1 else ""

    from core.skills import discover_skills, find_skill, execute_skill

    state = _resolve_runtime_state(agent)
    skills = discover_skills(Path.cwd())
    skill = find_skill(skills, name)
    if skill is None:
        _erase_live_line()
        console.print(f"[#ff5555]✗ Skill not found: {name}[/#]")
        return True

    if getattr(skill, "goal", "") or getattr(skill, "success_criteria", ""):
        from core.kernel.state import GoalSpec
        g_prompt = getattr(skill, "goal", "") or getattr(skill, "description", "") or skill.name
        g_crit = getattr(skill, "success_criteria", "") or g_prompt
        state.active_goal = GoalSpec(raw_prompt=g_prompt, success_criteria=g_crit, is_met=False)

    # Execute through ShellTool (Phase 2.1 heuristics + ToolResult evidence).
    result = execute_skill(skill, state=state, evidence_log=_resolve_evidence_log(agent))

    ok = bool(getattr(result, "success", False))
    color = "[#55ff55]" if ok else "[#ff5555]"
    out = getattr(result, "stdout", "") or getattr(result, "stderr", "") or ""
    if isinstance(out, str) and len(out) > 4000:
        out = out[-4000:]
    _erase_live_line()
    console.print(
        Panel(
            f"[#00ffff]SKILL[/] {skill.name}\n\n"
            f"{color}{out or '(no output)'}[/#]",
            border_style="#1a1a42",
            title=f"[#00ffff]◈ Skill Executed{' (OK)' if ok else ' (FAILED)'}[/]",
        )
    )
    return True


thought_compressor = LiveThoughtCompressor()

# Inject our custom "Core Breathing" spinner natively into Rich so the
# animation is rendered thread-safely through Console (no raw sys.stdout).
SPINNERS["cyber_core"] = {
    "interval": 200,
    "frames": ["◇", "◈", "◆", "◈"],
}

# Only the classes actually consumed by prompt_toolkit are kept.
# The boxed UI draws its borders/chevron via inline HTML (see run_repl),
# so the old 'prompt'/'bottom-toolbar' classes are dead and removed.
cyberpunk_style = Style.from_dict({
    "input": "ansicyan",
})

# Persisted command history (up/down arrows) — survives sessions.
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".nabd_repl_history")


async def render_agent_events(kinetic=None) -> None:
    """Async event consumer rendering agent stream events in Cyberpunk aesthetic.

    Runs for the whole REPL session (one task); survives per-turn 'done'
    sentinels so streaming works across multiple prompts. Cancelled on exit.
    """
    bridge = get_bridge()

    # Kinetic State Engine (atomic spinner + cyber-verbs). Shares this REPL's
    # console so the single live status line renders in the same terminal,
    # fully decoupled from the async event loop via its own spinner thread.
    if kinetic is None:
        from engine.kinetic import KineticStateEngine
        kinetic = KineticStateEngine(console=console)
        kinetic.wire()

    # Unified TODO view: the always-on box now redraws from the SAME
    # TodoManager stream the checklist (show_todo_list / on_plan_updated)
    # consumes — no second STATE.md parser, no duplicate box. The prior
    # code re-read STATE.md at prompt time, stacking a second TODO list
    # under the bus-driven one. RepositoryContextManager still writes
    # STATE.md for LMK resume; we only stopped rendering it twice.
    try:
        def _on_plan_updated(todos):
            _render_todo_from_plan(list(todos) if todos else [])
        bridge.subscribe("on_plan_updated", _on_plan_updated)
    except Exception:
        pass

    # Live thought compressor (module-level so the Ctrl+O binding can read
    # the same session_thoughts store). Collapses streaming reasoning into a
    # single dynamic line and freezes an immutable placeholder.
    compressor = thought_compressor

    # Ctrl+O expand handler: dump the latest raw thought block on demand.
    def _try_expand() -> None:
        try:
            if compressor.session_thoughts:
                last_id = next(reversed(compressor.session_thoughts))
                raw = compressor.session_thoughts[last_id]
                console.print(
                    Panel(
                        safe_strip(raw) or "(empty)",
                        title="[bento.thought.text]◈ Thought Process[/bento.thought.text]",
                        border_style="bento.thought.border",
                        box=BOX_THOUGHT,
                        padding=(1, 2),
                    )
                )
        except Exception:
            pass

    token_buf = ""
    held_buf = ""
    try:
        while True:
            # Periodically refresh the elapsed counter on the live line.
            compressor.tick()
            event = await bridge.get_event()
            if event is None:
                continue

            event_type = event.get("type")
            if event_type == "done":
                # Per-turn sentinel — stop kinetic when turn completes.
                if kinetic:
                    kinetic.stop()
                token_buf = ""
                held_buf = ""
                continue
            elif event_type == "thinking_start":
                # Begin the compressed thinking line for this turn.
                compressor.start()
                if kinetic:
                    kinetic.start()
                token_buf = ""
                held_buf = ""
                if hasattr(bridge, "_tokens_streamed"):
                    bridge._tokens_streamed = False
                continue
            elif event_type == "thinking_stop":
                # Conclude the thought phase (freeze placeholder + store raw).
                compressor.stop()
                if kinetic:
                    kinetic.stop()
                continue
            elif event_type == "thought":
                # Raw reasoning chunk: accumulate (do NOT stream multi-line).
                compressor.feed(event.get("content", ""))
                continue
            elif event_type == "tool_start":
                # Real work started: conclude any open thought phase, then
                # render a single-line high-contrast bento badge.
                compressor.stop()
                token_buf = ""
                held_buf = ""
                args = event.get("args", {})
                summary = args if isinstance(args, str) else str(args)
                badge = render_bento_badge(event.get("name", ""), summary)
                console.print(badge)
            elif event_type == "tool_end":
                # Avoid redundant double printing if TermuxBridgeUI on_tool_completed handles completion.
                summary = safe_strip(event.get("summary", ""))
                if summary and not summary.startswith("✓ Tool") and not getattr(bridge, "_on_tool_completed_active", False):
                    console.print(f"   [dim]↳ {summary}[/dim]")
            elif event_type == "token":
                content = event.get("content", "")
                token_buf += content
                stripped = token_buf.lstrip()
                if stripped.startswith("{") or stripped.startswith("final_answer"):
                    continue
                if "final_answer".startswith(stripped):
                    held_buf += content
                    continue
                to_print = held_buf + content
                held_buf = ""
                # The very first token means the agent began answering: stop
                # the thinking line before printing the response.
                compressor.stop()
                if hasattr(bridge, "_tokens_streamed"):
                    bridge._tokens_streamed = True
                console.print(to_print, end="", style="white")
    finally:
        # Defensive: guarantee no hanging live line on force-quit / shutdown.
        compressor.stop()
        if kinetic:
            kinetic.stop()


async def run_repl(agent, agent_runner_func=None) -> None:
    """Launch the Termux-optimized Sequential Cyberpunk REPL session.

    Runs an async event loop: prompt_async for input, a background consumer
    task for live agent streaming, and the blocking agent call offloaded to
    a worker thread (to_thread) so the UI bridge stays responsive.
    """
    # 1. Hard clear terminal (Termux specific)
    print("\033c", end="")

    # 2. Print Logo exactly once
    logo_ascii = "[#ffffff]█▄ █ ▄▀█ █▄▀ █▀▄ █▀▀ █▀█ █▀▄ █▀▀[/]\n[#808080]█ ▀█ █▀█ █▄█ █▄▀ █▄▄ █▄█ █▄▀ ██▄[/]"
    console.print(Align.center(logo_ascii))
    console.print()

    # 3. Print Status exactly once
    workspace_name = os.path.basename(os.getcwd())
    status_line = f"[#ffffff]System Ready[/] | [#808080]Model: gemini-1.5-pro[/] | [#808080]Workspace: {workspace_name}[/]"
    console.print(Align.center(status_line))
    console.print()

    bridge = get_bridge()

    # Global Ctrl+O: expand the most recent thought block on demand.
    bindings = KeyBindings()

    @bindings.add("c-o")
    def _(event) -> None:
        if thought_compressor.session_thoughts:
            last_id = next(reversed(thought_compressor.session_thoughts))
            raw = thought_compressor.session_thoughts[last_id]
            console.print("\n[#808080]── Thought Block ──[/]")
            console.print(safe_strip(raw) or "(empty)")

    session = PromptSession(style=cyberpunk_style, history=FileHistory(HISTORY_FILE), key_bindings=bindings)

    # Cache the border line per terminal width so it isn't rebuilt every turn.
    # Cost is O(width) and negligible, but caching avoids redundant allocation.
    _hr_cache: dict[int, str] = {}

    def _hr_line(width: int) -> str:
        line = _hr_cache.get(width)
        if line is None:
            line = f"<style color='#555555'>{'─' * width}</style>"
            _hr_cache[width] = line
        return line

    # Kinetic State Engine shared instance for REPL session
    from engine.kinetic import KineticStateEngine
    kinetic = KineticStateEngine(console=console)
    kinetic.wire()

    # 4. Start consumer task
    consumer_task = asyncio.create_task(render_agent_events(kinetic))

    try:
        # 5. Start the chat loop
        while True:
            # NO logo printing inside this loop!
            # Explicitly stop Kinetic UI status and compressor before asking for user input
            kinetic.stop()
            thought_compressor.stop()
            try:
                # Calculate width for the top separator
                term_width = shutil.get_terminal_size().columns - 1
                hr_style = _hr_line(term_width)

                # The top border and the prompt chevron
                render_todo_block()
                prompt_message = HTML(f"{hr_style}\n<b><style color='#ffffff'>❯</style></b> ")
                # Render the prompt without the buggy bottom_toolbar
                user_input = await session.prompt_async(
                    prompt_message,
                    placeholder="Ask your question..."
                )

                text = safe_strip(user_input)

                if text.lower() in ["exit", "quit"]:
                    console.print("[bold red]Exiting Nabd Agent OS cleanly...[/bold red]")
                    break
                if not text:
                    continue

                # 1. Capture clear/reset commands to wipe context, history, and evidence for a fresh task
                if text.lower() in ["/clear", "/reset", "/c", "clear"]:
                    if hasattr(agent, "clear_session"):
                        agent.clear_session()
                    else:
                        if hasattr(agent, "runtime_state") and hasattr(agent.runtime_state, "clear_context"):
                            agent.runtime_state.clear_context()
                        elif hasattr(agent, "state") and hasattr(agent.state, "clear_context"):
                            agent.state.clear_context()
                        elif hasattr(agent, "state") and hasattr(agent.state, "messages"):
                            msgs = agent.state.messages
                            sys_msgs = [m for m in msgs if m.get("role") == "system"] if msgs else []
                            agent.state.set_messages(sys_msgs)
                            agent.state.reset_step_count()
                        if hasattr(agent, "evidence_log") and agent.evidence_log is not None:
                            if hasattr(agent.evidence_log, "clear"):
                                agent.evidence_log.clear()
                            elif isinstance(agent.evidence_log, list):
                                agent.evidence_log.clear()

                    kinetic.stop()
                    thought_compressor.stop()
                    console.print("\n[bold green]✨ [System] Context, history, and evidence have been cleared. Ready for a new task![/bold green]\n")
                    continue

                # ── Phase5 (Permissions) slash commands ───────────────────────
                # Intercept allow/deny/clear_perms BEFORE invoking the agent so the
                # permission policy can be adjusted mid-session. These rules are
                # transient (stored on RuntimeState.shell_permissions) and reset on
                # a hard restart. They do NOT bypass the Phase 2.1 heuristics.
                if _handle_permission_command(text, agent):
                    kinetic.stop()
                    thought_compressor.stop()
                    continue

                # ── Phase5 (GoalSpec) /goal command ──────────────────────────
                # Intercept /goal BEFORE invoking the agent so we can print a
                # clean, non-transient confirmation block (Intent vs Criteria)
                # rather than letting the raw command flow into the task stream.
                if _handle_goal_command(text, agent):
                    kinetic.stop()
                    thought_compressor.stop()
                    continue

                # ── Phase 6 (Native Skills Loader) /skill command ────────────
                # Intercept /skill BEFORE invoking the agent so the declarative
                # skill command runs through ShellTool.execute() — preserving the
                # Phase 2.1 heuristic sweep, the ToolResult evidence, and the
                # PermissionEngine ALLOW integration — instead of being treated
                # as a natural-language task.
                if _handle_skill_command(text, agent):
                    kinetic.stop()
                    thought_compressor.stop()
                    continue

                # Stable task id for this turn's real-time lifecycle tracking.
                task_id = RepositoryContextManager.task_id_for(text)

                # Call 1 (Start): mark the task active BEFORE invoking the agent.
                # Best-effort + guarded so a write failure never blocks the turn.
                try:
                    RepositoryContextManager().update_state(task_id, "In Progress", {"prompt": text})
                except Exception:
                    pass

                await bridge.emit_thinking_start()
                kinetic.start()

                # Reset final answer rendered tracker before each turn
                bus_ref = getattr(agent, "bus", None) or getattr(bridge, "event_bus", None)
                if bus_ref:
                    bus_ref._final_answer_rendered = False

                # Offload the blocking agent.run to a worker thread so the
                # event loop keeps streaming tool/token events concurrently.
                try:
                    if agent_runner_func and agent is not None:
                        response_text = await asyncio.to_thread(
                            agent_runner_func, text, agent
                        )
                    elif agent_runner_func:
                        response_text = await asyncio.to_thread(agent_runner_func, text)
                    else:
                        response_text = await asyncio.to_thread(agent.run, text)
                except Exception as e:
                    # Agent execution failed (API timeout, rate limit, etc.).
                    # Notify the bridge explicitly so the spinner stops instead
                    # of hanging silently. The bridge is the single owner of UI
                    # state, so we route the stop through it — never leave the
                    # spinner dangling from an unhandled worker-thread error.
                    console.print(
                        Panel(
                            Markdown(f"⚠️ **Execution failed:** `{type(e).__name__}`\n\n{str(e)}"),
                            border_style="red",
                            title="[bold red]❌ Agent Error[/]",
                        )
                    )
                    continue
                finally:
                    # Forcefully kill the spinner after EVERY interaction —
                    # success, failure, or empty-string return (no exception).
                    await bridge.emit_thinking_stop()
                    kinetic.stop()
                    thought_compressor.stop()

                if not (bus_ref and getattr(bus_ref, "_final_answer_rendered", False)) and not (bus_ref and getattr(bus_ref, "_tokens_streamed", False)):
                    clean_resp = extract_clean_answer(response_text)
                    if clean_resp:
                        console.print(
                            Panel(
                                Markdown(clean_resp),
                                border_style="bento.final.border",
                                box=BOX_FINAL,
                                padding=(1, 2),
                                title="[bento.final.title] ◈ Agent [/bento.final.title]",
                            )
                        )

                # Call 2 (Finish): transition the task to Completed immediately
                # after the agent's response is rendered. Best-effort + guarded.
                try:
                    RepositoryContextManager().update_state(task_id, "Completed", {"prompt": text})
                except Exception:
                    pass

            except (KeyboardInterrupt, EOFError):
                thought_compressor.stop()
                console.print("\n[bold red]Session terminated cleanly.[/bold red]")
                break
    finally:
        # Graceful shutdown: stop the streaming consumer.
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        # Tear down the Kinetic State Engine (clears the live status line).
        try:
            kinetic.stop()
        except Exception:
            pass


main = run_repl


def extract_clean_answer(raw_text: Any) -> str:
    """استخراج النص النقي والمصفى من أي رد سواء كان JSON أو Dict أو نص مهيكل"""
    if raw_text is None:
        return ""
    if isinstance(raw_text, dict):
        if "answer" in raw_text:
            return str(raw_text["answer"])
        if "output" in raw_text:
            return str(raw_text["output"])
        for sub_key in ("args", "arguments"):
            sub = raw_text.get(sub_key)
            if isinstance(sub, dict) and "answer" in sub:
                return str(sub["answer"])
        return str(raw_text)

    text = safe_strip(raw_text)
    if not text:
        return ""

    # 1. محاولة فك تشفير النص كـ JSON كامل
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            if "answer" in parsed:
                return str(parsed["answer"])
            if "output" in parsed:
                return str(parsed["output"])
            for sub_key in ("args", "arguments"):
                sub = parsed.get(sub_key)
                if isinstance(sub, dict) and "answer" in sub:
                    return str(sub["answer"])
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. إذا فشل، نستخدم Regex ذكي لالتقاط المحتوى داخل مفتاح "answer"
    match = re.search(r'["\']answer["\']\s*:\s*["\'](.*?)["\'](?:\s*[,}\]])', text, re.DOTALL)
    if not match:
        match = re.search(r'["\']answer["\']\s*:\s*["\'](.*?)["\']\s*$}?', text, re.DOTALL)
    if match:
        val = match.group(1)
        val = val.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")
        return val

    return text


class TerminalVisualizer:
    """المسؤول عن التقاط أحداث الـ Event Bus وتحويلها إلى لوحات بصرية متحركة داخل Termux"""

    def __init__(self, event_bus, state):
        self.event_bus = event_bus
        self.state = state
        self.live_context = None
        if self.event_bus:
            self.event_bus._final_answer_rendered = False
        self._register_listeners()

    def _register_listeners(self):
        """ربط الأحداث بالدالات البصرية المناسبة لها مع دعم دالتي on و subscribe"""
        register_fn = getattr(self.event_bus, "on", None) or getattr(self.event_bus, "subscribe", None)
        if register_fn:
            self.event_bus._on_tool_completed_active = True
            register_fn("tool_started", self.on_tool_started)
            register_fn("tool_completed", self.on_tool_completed)
            register_fn("agent_handoff", self.on_agent_handoff)
            register_fn("tool_auth_violation", self.on_tool_auth_violation)
            register_fn("show_final_answer", self.on_final_answer)

    def on_tool_started(self, data: dict):
        """إظهار سبينر متحرك عند بدء تشغيل أي أداة بناءً على دور الوكيل"""
        try:
            self.stop()  # إيقاف أي سياق عرض نشط أولاً

            role = data.get("role", "ORCHESTRATOR")
            # The engine emits "tool" consistently (see engine/dispatcher.py).
            tool_name = data.get("tool") or "tool"

            # اختيار لون السبينر حسب قبعة الوكيل الحالي
            color = "cyan" if role == "ORCHESTRATOR" else "green" if role == "CODER" else "yellow"

            spinner = Spinner("dots", text=Text(f" [{role}] Running tool: {tool_name}...", style=f"bold {color}"))

            # تفعيل العرض الحي المتحرك في الطرفية بشكل مؤقت
            self.live_context = Live(spinner, console=console, refresh_per_second=10, transient=True)
            self.live_context.start()
        except Exception as exc:
            # Never let a UI rendering glitch crash the event bus / tool pipeline.
            try:
                console.print(f"[dim red][UI] tool spinner unavailable: {exc}[/][/]")
            except Exception:
                pass

    def on_tool_completed(self, data: dict):
        """إيقاف السبينر وطباعة نتيجة الأداة بنجاح"""
        try:
            self.stop()
            tool_name = data.get("tool") or "?"
            console.print(f"[bold green]✓[/bold green] Tool [bold white]{tool_name}[/] completed successfully.")
        except Exception as exc:
            try:
                console.print(f"[dim red][UI] tool completion render failed: {exc}[/][/]")
            except Exception:
                pass

    def on_agent_handoff(self, data: dict):
        """طباعة لوحة أنيقة توضح انتقال "الوعي" والمسؤولية بين الوكلاء"""
        self.stop()

        from_role = data.get("from_role")
        to_role = data.get("to_role")
        payload = data.get("payload", "")

        handoff_text = Text()
        handoff_text.append("🔄 Handoff Protocol: ", style="bold white")
        handoff_text.append(f"{from_role}", style="bold cyan" if from_role == "ORCHESTRATOR" else "bold green")
        handoff_text.append(" ➡️ ", style="bold blink white")
        handoff_text.append(f"{to_role}\n\n", style="bold yellow" if to_role == "AUDITOR" else "bold green")
        handoff_text.append("📋 Payload:\n", style="dim white")
        handoff_text.append(f"\"{payload}\"", style="italic dim")

        panel = Panel(handoff_text, border_style="bento.execution.border", box=BOX_EXECUTION, padding=(1, 2), title="[bento.execution.title] 🔄 Agent Context Handoff [/bento.execution.title]")
        console.print(panel)

    def on_tool_auth_violation(self, data: dict):
        """وميض تحذيري أحمر صارم عند محاولة خرق الصلاحيات"""
        self.stop()

        error_msg = data.get("error", "Unknown Violation")
        role = data.get("role")
        tool = data.get("tool")

        violation_text = (
            "[bold white on red] 🚨 EXECUTION GATE BLOCK [/bold white on red]\n\n"
            "[bold red]Security Violation Detected![/bold red]\n"
            f"• Agent: [bold yellow]{role}[/]\n"
            f"• Forbidden Tool: [bold cyan]{tool}[/]\n"
            f"• Details: [dim]{error_msg}[/]"
        )
        panel = Panel(violation_text, border_style="red", expand=False)
        console.print(panel)

    def on_final_answer(self, data: dict):
        """طباعة الرد النهائي الموجه لك بتأثير الكتابة التدريجية الحي والتهوية البصرية"""
        self.stop()

        raw_output = data.get("output", data.get("answer", ""))
        output = extract_clean_answer(raw_output)
        if not output:
            return

        if self.event_bus:
            self.event_bus._final_answer_rendered = True

        # 1. حساب العرض الآمن والمناسب لشاشة الهاتف في Termux (نترك هامش 4 أحرف لمنع الالتصاق)
        safe_width = min(console.size.width - 4, 80)

        # 2. تهيئة الإطار الفارغ مع التنسيقات المستديرة والهوامش الداخلية
        current_text = ""
        panel = Panel(
            Markdown(current_text),
            border_style="bento.final.border",
            box=BOX_FINAL,
            padding=(1, 2),
            width=safe_width,
            title="[bento.final.title] 🌿 Nabd OS [/bento.final.title]",
            subtitle="[dim]Task completed successfully[/dim]",
            subtitle_align="right"
        )

        console.print("\n")  # سطر فارغ لتهوية الجزء العلوي قبل انبثاق اللوحة

        # 3. تأثير التدفق التدريجي (Streaming Effect)
        # نقوم بتقسيم النص إلى كلمات وطباعتها على دفعات خفيفة للحفاظ على جمالية الماركدوان والسرعة
        words = output.split(" ")
        chunk_size = 3  # عدد الكلمات المطبوعة في كل نبضة

        with Live(panel, console=console, auto_refresh=False) as live:
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                current_text += (" " if current_text else "") + chunk

                # تحديث عرض الماركدوان تدريجياً داخل لوحة العرض الحي
                panel.renderable = Markdown(current_text)
                live.update(panel, refresh=True)

                # تأخير زمني بسيط بالملي ثانية ليحاكي سرعة الاستجابة الحية
                time.sleep(0.04)

        console.print("\n")  # سطر فارغ لتهوية الجزء السفلي بعد اكتمال اللوحة

    def stop(self):
        """🔒 إغلاق آمن لعرض الـ Live لمنع تعليق الطرفية"""
        if self.live_context:
            try:
                self.live_context.stop()
            except Exception:
                pass
            self.live_context = None


if __name__ == "__main__":
    from core.agent_manager import initialize_secure_agent

    asyncio.run(run_repl(agent=initialize_secure_agent()))
