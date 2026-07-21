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
from ui.live_thought import LiveThoughtCompressor
from core.utils import safe_strip
import tools.file_system as _fs_module
from ui.theme import (
    nabd_theme,
    BOX_THOUGHT,
    BOX_EXECUTION,
    BOX_EVIDENCE,
    BOX_FINAL,
    PALETTE,
    PANEL_STYLES,
    CUSTOM_THEME,
    PROMPT_STYLE,
)

console = Console(theme=CUSTOM_THEME)

_last_echoed_input: str = ""


def echo_user_input(text: str) -> None:
    # No-op: PromptSession already displays prompt and user input cleanly.
    pass


def _ui_looks_like_tool_call(text: str) -> bool:
    """UI-side mirror of engine.loop._looks_like_tool_call.

    True when ``text`` is (or contains) a raw tool-call JSON — e.g. the last
    model response was another tool invocation rather than a real report. The
    FINAL ANSWER card and the streaming renderer must NEVER draw such payloads;
    this is the last wall that catches any leak from the loop/streaming paths.
    """
    if not text:
        return False
    candidates = [text.strip()]
    for m in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        candidates.append(m)
    brace = text.find("{")
    if brace != -1:
        candidates.append(text[brace:])
    for cand in candidates:
        cand = cand.strip()
        if not cand.startswith("{"):
            continue
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            end = cand.rfind("}")
            if end != -1:
                try:
                    obj = json.loads(cand[: end + 1])
                except (json.JSONDecodeError, TypeError):
                    continue
            else:
                continue
        if isinstance(obj, dict) and "tool" in obj:
            return True
    return False


def _strip_tool_call_lines(text: str) -> str:
    """Remove lines containing raw tool-call JSON from mixed content.

    When the agent response contains text mixed with tool-call payloads
    (e.g. a file read followed by planned edits), this strips only the
    tool-call lines and keeps the readable text for the FINAL ANSWER box.
    Never shows ERROR ENGINE for mixed content — only real exceptions.

    Additionally strips common raw-output patterns that the agent sometimes
    pastes verbatim into the answer: tool log entries, raw docstrings,
    ``from __future__`` imports, and similar code-dump lines.

    Returns the text with tool-call lines removed. Lines matching:
      - ``{"tool": ...`` JSON payloads
      - ```json ... ``` fenced blocks containing tool calls
      - ``{ "tool": ...`` (whitespace-prefixed)
      - ``- [tool_name] ...`` tool log entries
      - triple-quote blocks (standalone \"\"\" or \'\'\')
      - ``from __future__`` raw import lines
    Are identified and removed individually; surrounding text is preserved.
    """
    if not text:
        return ""
    lines = text.splitlines()
    result: list[str] = []
    inside_json_fence = False
    inside_triple_quote = False
    for line in lines:
        stripped = line.strip()

        # ── Check for JSON fence FIRST (prevents triple-quote hijacking) ──
        if stripped.startswith("```") and ("json" in stripped.lower() or inside_json_fence):
            if inside_json_fence:
                inside_json_fence = False  # closing fence
                continue
            inside_json_fence = True  # opening fence
            continue
        if inside_json_fence:
            continue

        # ── Track and skip triple-quote blocks (raw docstring dumps) ─────
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if inside_triple_quote:
                inside_triple_quote = False  # closing triple quote
                continue
            inside_triple_quote = True  # opening triple quote
            continue
        if inside_triple_quote:
            continue

        # ── Skip raw tool-log entries: "- [tool_name] ..." ──────────────
        if stripped.startswith("- [") and "]" in stripped[3:]:
            continue

        # ── Skip raw import / code-dump lines ────────────────────────────
        if stripped.startswith("from __future__"):
            continue
        if stripped.startswith("import ") and " as " not in stripped:
            # Only skip bare imports, not sentences that happen to start with "import"
            if len(stripped) < 80 and not stripped.endswith("."):
                continue

        # ── Check if the line is a standalone tool-call or output JSON ──
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict) and ("tool" in obj or "output" in obj):
                    continue  # skip this line — it's a tool/output JSON
            except (json.JSONDecodeError, TypeError):
                pass

        # ── Check for trailing JSON at END of line (not mid-line code) ──
        brace = line.rfind('{"tool"')
        if brace != -1:
            after = line[brace:].strip()
            if after.endswith("}") or after.endswith("}]"):
                before = line[:brace].rstrip()
                if before:
                    result.append(before)
                continue

        # ── Normal line — keep it ───────────────────────────────────────
        result.append(line)

    # Join and strip trailing whitespace
    clean = "\n".join(result).strip()
    return clean


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
    # TODOS badge using Rich markup (green background per _BADGE_STYLES).
    badge_style = _BADGE_STYLES.get("TODOS", "bold white on #059669")
    console.print()
    console.print(f"[{badge_style}] TODOS [/] [cyan]{total} items[/]")
    for task in in_progress:
        text = task.get("content", task.get("text", ""))
        console.print(f"[green]□ {text}[/]")
    for task in completed:
        text = task.get("content", task.get("text", ""))
        console.print(f"[green strike]☑ {text}[/]")


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

# ── Mode cycling (Shift+Tab): normal → plan mode → accept edits → normal ──
# 0 = normal, 1 = plan mode, 2 = accept edits
_mode_state: int = 0
_plan_mode: bool = False

# ── Status spinner state (Stage 2) ──────────────────────────────────────────
# Rotated in the bottom toolbar at 120ms. Phase is set by render_agent_events.
_STATUS_SPINNER_FRAMES: list[str] = ["◇", "◈", "◆", "☆", "★", "○", "●"]
_STATUS_SPINNER_IDX: int = 0

_STATUS_PHASE_VERBS: dict[str, str] = {
    "thinking": "Sketching",
    "reading":  "Reviewing",
    "writing":  "Channeling",
    "shell":    "Resolving",
    "search":   "Contemplating",
    "reasoning":"Threading",
    "git":      "Inspecting",
    "finish":   "Articulating",
    "idle":     "Drafting",
}

_status_phase: str = "idle"
_status_tokens: int = 0


def _set_status_phase(phase: str) -> None:
    """Update the bottom-toolbar spinner phase."""
    global _status_phase
    _status_phase = phase


def _add_status_tokens(count: int) -> None:
    """Accumulate token count for the bottom-toolbar display."""
    global _status_tokens
    _status_tokens += count


def _action_to_phase(action: str) -> str:
    """Map a print_badge action to a status spinner phase verb."""
    a = action.upper().strip()
    if a in ("READ", "EXPLORE"):
        return "reading"
    if a in ("EDIT", "WRITE"):
        return "writing"
    if a == "SHELL":
        return "shell"
    if a in ("SEARCH", "RAG", "MEMORY"):
        return "search"
    if a == "TODOS":
        return "reading"
    if a == "GIT":
        return "git"
    return "thinking"

# ── Arabic scan keywords — auto-trigger EXPLORE tool ────────────────────
# When the user types "فحر مستودع" (or similar), the agent may not
# produce tool calls naturally. We detect the intent and seed the
# agent's context with a live directory listing + evidence record.
_ARABIC_SCAN_KEYWORDS: list[str] = [
    "فحر",      # colloquial Egyptian "scan"
    "افحص",     # standard Arabic "scan/inspect"
    "فحص",      # "inspection"
    "مسح",      # "scan"
    "استكشاف",  # "explore"
    "كشف",      # "discover"
    "دقق",      # "scrutinize"
    "دقّق",     # "scrutinize" (with shadda)
    "طالع",     # "review"
]


def _detect_arabic_scan_intent(text: str) -> bool:
    """Return True if *text* contains an Arabic repository scan verb.

    Detects scan/inspect keywords like "فحر", "افحص", "استكشاف" etc.
    A target hint (repository, code, project) is NOT required — the
    scan keyword alone suffices for terse commands like "افحص".
    """
    if not text:
        return False
    normalized = " ".join(text.split())  # normalize whitespace
    return any(kw in normalized for kw in _ARABIC_SCAN_KEYWORDS)


def _maybe_auto_scan(text: str, agent: Any) -> bool:
    """If *text* contains Arabic scan intent, auto-trigger the EXPLORE tool.

    Seeds the agent's evidence log with a directory listing so that:
      1. The convergence gate (``_real_reads() >= 3``) sees real file records.
      2. The LLM gets concrete file paths to work with in its context.

    Returns True if an auto-scan was performed, False otherwise.
    """
    if not _detect_arabic_scan_intent(text):
        return False

    console.print(f"  [#00ffff]⟳ Auto-scan triggered — listing workspace...[/#]")
    _set_status_phase("reading")

    try:
        # Build the FileSystemTool with the current workspace.
        from tools.file_system import FileSystemTool
        from pathlib import Path as _Path
        fs_tool = FileSystemTool(workspace=_Path.cwd())

        # Perform a non-recursive listing of the workspace root.
        result = fs_tool.execute(action="list", path=".")
        if not result.success:
            console.print(f"  [#ff5555]✗ Auto-scan failed: {result.stderr}[/#]")
            return False

        output = (result.stdout or "").strip()
        if not output:
            console.print(f"  [#ffaa55]⚠ Auto-scan returned empty listing.[/#]")
            return False

        # ── Seed the agent's evidence log ────────────────────────────────
        # Add evidence records for the listing so _real_reads() sees them.
        # Uses EvidenceLog.record() — the canonical write path.
        evidence_log = getattr(agent, "evidence_log", None)
        if evidence_log is not None and hasattr(evidence_log, "record"):
            try:
                evidence_log.record(
                    tool="file_system",
                    command_or_path=".",
                    success=True,
                    output_snippet=output[:200],
                    action="list",
                )
            except Exception:
                pass  # evidence seeding is best-effort

        # ── Append results as a system message in agent context ──────────
        # This ensures the LLM sees the file listing before it attempts
        # to answer — it can then call read on specific files.
        state = _resolve_runtime_state(agent)
        if state is not None and hasattr(state, "append_message"):
            try:
                msg = (
                    "[CONTROL] Auto-scan: workspace listing was performed because "
                    "your request contained a scan command.\n\n"
                    f"Directory listing (workspace root):\n{output[:2000]}\n\n"
                    "You should now read specific files from this listing to "
                    "answer the user's request. Call file_system with "
                    "action='read' on relevant files."
                )
                state.append_message({"role": "system", "content": msg})
            except Exception:
                pass

        console.print(f"  [#55ff55]✓ Auto-scan completed — {len(output.splitlines())} entries found[/#]")
        return True

    except Exception as exc:
        console.print(f"  [#ff5555]✗ Auto-scan error: {exc}[/#]")
        return False


# ── Context warning threshold (Stage 6) ────────────────────────────────────
# When accumulated tokens exceed this, a warning with "try /compact" appears
# in the bottom toolbar.
_CONTEXT_WARN_THRESHOLD: int = 100_000

# ── Re-entrancy guard — prevents concurrent agent turns ────────────────────
_agent_busy: bool = False

PLAN_MODE_INSTRUCTION: str = (
    "You are in PLAN MODE. Before executing any task:\n"
    "1. Use todo_write(action='plan', items=[...]) to outline your steps\n"
    "2. Get confirmation via final_answer() showing your plan\n"
    "3. Only then proceed with execution\n"
)


def _cycle_mode() -> None:
    """Cycle through: normal → plan mode → accept edits → normal."""
    global _mode_state, _plan_mode
    _mode_state = (_mode_state + 1) % 3
    _plan_mode = (_mode_state == 1)
    # Sync the accept-edits flag in tools/file_system.py.
    _fs_module._accept_edits_enabled = (_mode_state == 2)
    # Clear any stale queue when toggling accept-edits OFF.
    if _mode_state != 2:
        _fs_module._accept_edits_pending.clear()


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


# ── Stage 8: /compact — conversation compaction ───────────────────────────
_COMPACT_MAX_TOKENS: int = 500


def _estimate_message_tokens(messages: list[dict]) -> int:
    """Rough token estimate: ~4 chars per token."""
    total_chars = sum(len(m.get("content", "") or "") for m in messages)
    return max(1, total_chars // 4)


def _handle_compact_command(agent: Any) -> bool:
    """Compact the agent's conversation history.

    Uses ``RuntimeState.prune_history()`` with a 500-token budget to
    replace verbose history with a compact form, then reports the
    token savings to the console.
    """
    state = _resolve_runtime_state(agent)
    if not state:
        _erase_live_line()
        console.print("[#ff5555]No agent state available for compaction.[/#]")
        return True

    old_messages = state.get_messages() if hasattr(state, "get_messages") else getattr(state, "messages", [])
    old_tokens = _estimate_message_tokens(old_messages)

    try:
        # Set a tight budget so prune_history reduces to ~500 tokens.
        saved_max = getattr(state, "max_context_tokens", 8192)
        if hasattr(state, "max_context_tokens"):
            state.max_context_tokens = _COMPACT_MAX_TOKENS
        if hasattr(state, "prune_history") and callable(state.prune_history):
            state.prune_history()
        elif hasattr(state, "clear_context") and callable(state.clear_context):
            state.clear_context()
        else:
            # Manual truncation: keep system + last 2 turns.
            msgs = getattr(state, "messages", [])
            if msgs:
                sys_msgs = [m for m in msgs if m.get("role") == "system"]
                non_sys = [m for m in msgs if m.get("role") != "system"]
                kept = sys_msgs + non_sys[-4:]
                state.messages = kept
        # Restore original budget.
        if hasattr(state, "max_context_tokens"):
            state.max_context_tokens = saved_max
    except Exception as exc:
        _erase_live_line()
        console.print(f"[#ff5555]Compaction failed: {exc}[/#]")
        return True

    new_messages = state.get_messages() if hasattr(state, "get_messages") else getattr(state, "messages", [])
    new_tokens = _estimate_message_tokens(new_messages)
    saved = old_tokens - new_tokens

    _erase_live_line()
    console.print(f"[bold #00ff00]✓[/] [dim]Context compacted:[/] [cyan]~{old_tokens}t → ~{new_tokens}t[/] [dim](saved ~{saved}t)[/dim]")
    if saved > 0:
        console.print(f"  [dim]↳ Run /compact again if context grows too large[/dim]")
    else:
        console.print(f"  [dim]↳ Context already within budget[/dim]")
    return True


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

# ── Action badge colors (Stage 1: print_badge) ───────────────────────────
# Color mapping per the UI overhaul spec:
#   READ   → blue  (#0891B2 teal)
#   EDIT   → blue  (#0891B2 teal)
#   SHELL  → orange (#D97706)
#   SEARCH → purple (#7C3AED)
#   EXPLORE→ purple (#7C3AED)
#   TODOS  → green  (#059669)
_BADGE_STYLES: dict[str, str] = {
    "READ":    "bold white on #0891B2",
    "EDIT":    "bold white on #0891B2",
    "SHELL":   "bold black on #D97706",
    "SEARCH":  "bold white on #7C3AED",
    "EXPLORE": "bold white on #7C3AED",
    "TODOS":   "bold white on #059669",
    "WRITE":   "bold white on #0891B2",
    "RAG":     "bold white on #7C3AED",
    "MEMORY":  "bold white on #7C3AED",
    "GIT":     "bold white on #059669",
    "KILL":    "bold black on #EF4444",
    "DEFAULT": "bold white on #0891B2",
}


def _parse_tool_event(tool_name: str, args: dict) -> tuple[str, str, str]:
    """Parse a tool_start event into (action, label, meta) for print_badge.

    Args:
        tool_name: The tool name (e.g. "file_system", "execute_shell").
        args: The tool arguments dict.

    Returns:
        (action, label, meta) tuple:
        - action: badge label (READ, EDIT, SHELL, SEARCH, TODOS, …)
        - label:  primary content (file path, command, query)
        - meta:   secondary metadata (line count, stats)
    """
    name = (tool_name or "").lower()
    action_args: dict = args if isinstance(args, dict) else {}

    # File system tool — inspect the 'action' sub-field.
    if name in ("file_system", "file"):
        file_action = str(action_args.get("action", "")).lower()
        path = str(action_args.get("path", ""))
        if file_action in ("read",):
            return ("READ", path, "")
        if file_action in ("edit",):
            return ("EDIT", path, "")
        if file_action in ("write",):
            return ("WRITE", path, "")
        if file_action in ("replace", "append"):
            return ("EDIT", path, "")
        if file_action == "read_many":
            return ("READ", path, "")
        if file_action == "list":
            return ("EXPLORE", path, "")
        return ("READ", path, "")

    # Shell / execution tools.
    if "shell" in name or "exec" in name or name == "bash":
        cmd = str(action_args.get("command", "") or action_args.get("cmd", "") or "")
        return ("SHELL", cmd, "")

    # Search tools (web, rag, knowledge).
    if "search" in name or "web" in name or "rag" in name or "knowledge" in name:
        query = str(action_args.get("query", "") or "")
        return ("SEARCH", query, "")

    # TODO tools.
    if "todo" in name:
        return ("TODOS", "", "")

    # Memory tools.
    if "memory" in name:
        query = str(action_args.get("query", "") or "")
        return ("MEMORY", query, "")

    # Git inspector tools.
    if "git" in name:
        git_action = str(action_args.get("action", ""))
        return ("GIT", git_action, "")

    # Fallback: use the tool name as the label.
    return ("DEFAULT", tool_name or "", "")


def print_badge(action: str, label: str = "", meta: str = "") -> None:
    """Print a colored action badge line using Rich markup.

    Color is determined by the ``action`` parameter per the global style map.
    The badge appears exactly once per tool execution, never duplicated.

    Examples::

        READ  core/loop.py 381 lines
        EDIT  engine.py +12 -3
        SHELL python3 main.py
        SEARCH dependency graph
        TODOS [4 items]

    Args:
        action: Action type (READ, EDIT, SHELL, SEARCH, EXPLORE, TODOS, …).
        label:  Primary content text (file path, command, query).
        meta:   Optional secondary metadata (line count, diff stats).
    """
    action = action.upper().strip()
    style = _BADGE_STYLES.get(action, _BADGE_STYLES["DEFAULT"])
    badge_text = f"[{style}] {action} [/]"

    parts: list[str] = [f" {badge_text}"]
    if label:
        parts.append(label)
    if meta:
        parts.append(f"[dim]{meta}[/dim]")

    console.print(" ".join(parts))


# ── Collapsible output (Stage 5: shared collapse manager, threshold 5) ────
# Stores full content of collapsed blocks for Ctrl+O expansion.
_collapsed_blocks: list[str] = []


def _print_collapsible(
    lines: list[str],
    *,
    prefix: str = "",
    line_style: str = "dim",
    max_lines: int = 5,
    fold_hint: str = "[ctrl+o to expand]",
) -> None:
    """Print content lines collapsed to *max_lines*, storing full text for expand.

    If *lines* has ``max_lines`` or fewer, all lines are printed.
    If more, only the first ``max_lines`` are shown, followed by
    a fold indicator.  The full content is pushed onto
    ``_collapsed_blocks`` so Ctrl+O can retrieve it.

    Args:
        lines: Content lines to display.
        prefix: Optional prefix printed before each line (e.g. ``::``).
        line_style: Rich style applied to each line (e.g. ``"dim"``).
        max_lines: Collapse threshold.
        fold_hint: Hint text shown in the fold indicator.
    """
    if not lines:
        return
    show = lines[:max_lines]
    for line in show:
        if prefix:
            console.print(f"[{line_style}]{prefix} {line}[/]")
        else:
            console.print(f"[{line_style}]{line}[/]")
    if len(lines) > max_lines:
        extra = len(lines) - max_lines
        console.print(f"[{line_style}]... (+{extra} more lines, {fold_hint})[/]")
        # Store full content for Ctrl+O expansion (limit to 10 blocks).
        full = "\n".join(lines)
        _collapsed_blocks.append(full)
        if len(_collapsed_blocks) > 10:
            _collapsed_blocks.pop(0)


# ── Reasoning display (Stage 3 → Stage 5: 5-line threshold) ─────────────
def _display_thought_content(compressor: LiveThoughtCompressor) -> None:
    """Print collapsed thought content with ``::`` italic dim prefix.

    If the thought has 5 or fewer lines, all lines are shown.  If it has
    more, only the first 5 are printed followed by a fold indicator.
    The full thought can be expanded via Ctrl+O.

    Format::

        :: first line of reasoning
        :: second line
        :: third line
        :: fourth line
        :: fifth line
        ... (+5 more lines, [ctrl+o to expand])
    """
    if not compressor.session_thoughts:
        return
    try:
        last_id = next(reversed(compressor.session_thoughts))
    except (StopIteration, RuntimeError):
        return
    raw = compressor.session_thoughts.get(last_id, "")
    if not raw:
        return

    lines = safe_strip(raw).splitlines()
    if not lines:
        return

    _print_collapsible(lines, prefix="::", line_style="italic dim #00ffff", max_lines=5)


# ── Accept-edits processing ────────────────────────────────────────────────
# Note: Only the `edit` action flows through the pending queue. The `write`,
# `append`, and `replace` actions write immediately regardless of mode.
# This matches the user's spec: accept edits for the `edit` action only.


def _process_pending_edits() -> None:
    """Prompt user to accept/reject each pending edit from the agent turn.

    Each pending edit is displayed with its diff, enhanced with word-level
    highlighting via ``_fs_module._highlight_word_changes()``. The user types:
      Y/Enter → accept (write to disk)
      N      → reject (discard)
      S      → reject all remaining
    """
    pending = _fs_module._accept_edits_pending
    if not pending:
        return

    console.print()
    for edit in list(pending):
        diff_lines = edit.diff.splitlines()
        # Build a coloured display using Rich markup with word-level
        # highlighting via difflib.SequenceMatcher.
        colored: list[str] = []
        i = 0
        while i < len(diff_lines):
            line = diff_lines[i]
            # Detect a change pair: - old line followed by + new line
            if (
                line.startswith("-") and not line.startswith("---")
                and i + 1 < len(diff_lines)
                and diff_lines[i + 1].startswith("+") and not diff_lines[i + 1].startswith("+++")
            ):
                old_line = line[1:].rstrip("\n")
                new_line = diff_lines[i + 1][1:].rstrip("\n")
                hl_old, hl_new = _fs_module._highlight_word_changes(old_line, new_line)
                colored.append(f"[red]-{hl_old}[/red]")
                colored.append(f"[green]+{hl_new}[/green]")
                i += 2
            elif line.startswith("+") and not line.startswith("+++"):
                colored.append(f"[green]{line}[/green]")
                i += 1
            elif line.startswith("-") and not line.startswith("---"):
                colored.append(f"[red]{line}[/red]")
                i += 1
            else:
                colored.append(f"[dim]{line}[/dim]")
                i += 1
        diff_text = "\n".join(colored)

        panel = Panel(
            diff_text if diff_text else "(no diff — new file)",
            title=f"[bold]📝 EDIT [{edit.path}]  +{edit.additions} -{edit.removals}[/bold]",
            border_style="cyan",
            padding=(1, 2),
            width=min(console.width - 2, 80),
        )
        console.print(panel)

        # Prompt for acceptance.
        try:
            answer = input(f"  Accept edit '{edit.path}'? [Y/n/s(kip all)]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer == "s":
            console.print(f"  [dim]Skipped all remaining edits.[/dim]")
            break
        if answer == "n":
            console.print(f"  [dim]Rejected edit for '{edit.path}'.[/dim]")
            continue

        # Default / Y → write the edit to disk using the workspace-resolved path.
        write_target = Path(edit.resolved_path)
        write_target.parent.mkdir(parents=True, exist_ok=True)
        write_target.write_text(edit.new_content, encoding="utf-8")
        console.print(f"  [green]✓ Accepted edit for '{edit.path}' (+{edit.additions} -{edit.removals})[/green]")

    pending.clear()
    console.print()


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

    # Ctrl+O expand handler: dump the latest collapsed block (thought or tool output).
    def _try_expand() -> None:
        try:
            # Prefer tool output from the shared collapsed_blocks store.
            if _collapsed_blocks:
                raw = _collapsed_blocks[-1]
                console.print(
                    Panel(
                        raw or "(empty)",
                        title="[bento.execution.title]◈ Expanded Output[/bento.execution.title]",
                        border_style="bento.execution.border",
                        box=BOX_EXECUTION,
                        padding=(1, 2),
                    )
                )
            elif compressor.session_thoughts:
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
    # Streaming line buffer for pattern-filtered output.
    # Local variable: holds partial lines between tokens so complete
    # lines can be checked through _strip_tool_call_lines() before
    # being printed. Prevents tool-call patterns like ``- [tool_name]``
    # or ``from __future__`` from appearing momentarily on screen.
    _stream_line_buf = ""

    def _flush_local_stream() -> None:
        """Inline flush: print any clean content remaining in the line buffer."""
        nonlocal _stream_line_buf
        if not _stream_line_buf:
            return
        clean = _strip_tool_call_lines(_stream_line_buf)
        if clean:
            _erase_live_line()
            console.print(clean, end="", style="white")
        _stream_line_buf = ""

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
                _set_status_phase("idle")
                # Flush any remaining streaming buffer before resetting.
                _flush_local_stream()
                token_buf = ""
                held_buf = ""
                _stream_line_buf = ""
                continue
            elif event_type == "thinking_start":
                # Begin the compressed thinking line for this turn.
                compressor.start()
                if kinetic:
                    kinetic.start()
                _set_status_phase("thinking")
                token_buf = ""
                held_buf = ""
                _stream_line_buf = ""
                if hasattr(bridge, "_tokens_streamed"):
                    bridge._tokens_streamed = False
                continue
            elif event_type == "thinking_stop":
                # Conclude the thought phase (freeze placeholder + store raw).
                compressor.stop()
                # Display collapsed reasoning with :: prefix (Stage 3).
                _display_thought_content(compressor)
                if kinetic:
                    kinetic.stop()
                _set_status_phase("idle")
                continue
            elif event_type == "thought":
                # Raw reasoning chunk: accumulate (do NOT stream multi-line).
                compressor.feed(event.get("content", ""))
                _set_status_phase("reasoning")
                continue
            elif event_type == "tool_start":
                # Real work started: flush any partial stream text, conclude
                # any open thought phase, then render a single-line colored
                # action badge via print_badge.
                # Badge appears exactly once per tool execution (no duplication).
                _flush_local_stream()
                compressor.stop()
                token_buf = ""
                held_buf = ""
                _stream_line_buf = ""
                tool_name = event.get("name", "")
                args = event.get("args", {})
                action, label, meta = _parse_tool_event(tool_name, args or {})
                print_badge(action, label, meta)
                _set_status_phase(_action_to_phase(action))
            elif event_type == "tool_end":
                # Flush any partial streaming line before showing tool output.
                _flush_local_stream()
                # Avoid redundant double printing if TermuxBridgeUI on_tool_completed handles completion.
                _other_renderer_active = getattr(bridge, "_on_tool_completed_active", False)
                # Show collapsible output when available (Stage 5).
                if not _other_renderer_active:
                    output = safe_strip(event.get("output", ""))
                    if output:
                        out_lines = output.splitlines()
                        _print_collapsible(out_lines, prefix="", max_lines=5)
                summary = safe_strip(event.get("summary", ""))
                if summary and not summary.startswith("✓ Tool") and not _other_renderer_active:
                    console.print(f"   [dim]↳ {summary}[/dim]")
            elif event_type == "token":
                content = event.get("content", "")
                # Count tokens as they stream in for the live status line.
                compressor.add_tokens(len(content))
                _add_status_tokens(len(content))
                token_buf += content
                stripped = token_buf.lstrip()
                if stripped.startswith("{") or stripped.startswith("final_answer"):
                    continue
                if "final_answer".startswith(stripped):
                    held_buf += content
                    continue

                # ── Streaming filter: buffer complete lines, strip patterns ──
                # Merge any held-buffer content (from the final_answer guard
                # phase) into the streaming line buffer.
                if held_buf:
                    content = held_buf + content
                    held_buf = ""

                _stream_line_buf += content
                # Process complete lines (separated by \n).
                while "\n" in _stream_line_buf:
                    line, _stream_line_buf = _stream_line_buf.split("\n", 1)
                    clean_line = _strip_tool_call_lines(line)
                    if clean_line:
                        # First visible token: stop the thinking line.
                        compressor.stop()
                        _set_status_phase("finish")
                        if hasattr(bridge, "_tokens_streamed"):
                            bridge._tokens_streamed = True
                        _erase_live_line()
                        console.print(f"{clean_line}\n", end="", style="white")
                # Partial line (no trailing \n) stays in _stream_line_buf.
    finally:
        # Defensive: guarantee no hanging live line on force-quit / shutdown.
        compressor.stop()
        if kinetic:
            kinetic.stop()


async def _toolbar_spinner_loop() -> None:
    """Background task: rotate the toolbar spinner frame every 120ms.

    The prompt_toolkit bottom toolbar (``_get_toolbar``) reads the global
    ``_STATUS_SPINNER_IDX`` to determine which icon to show. This loop
    advances the index and invalidates the app so the toolbar redraws.
    """
    global _STATUS_SPINNER_IDX
    try:
        while True:
            await asyncio.sleep(0.12)
            _STATUS_SPINNER_IDX = (_STATUS_SPINNER_IDX + 1) % len(_STATUS_SPINNER_FRAMES)
            try:
                from prompt_toolkit.application import get_app
                get_app().invalidate()
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


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
        # Expand the most recent collapsed block (tool output or thought).
        if _collapsed_blocks:
            raw = _collapsed_blocks[-1]
            console.print(Panel(
                raw or "(empty)",
                title="[bento.execution.title] ◈ Expanded Output [/bento.execution.title]",
                border_style="bento.execution.border",
                box=BOX_EXECUTION,
                padding=(1, 2),
            ))
        elif thought_compressor.session_thoughts:
            last_id = next(reversed(thought_compressor.session_thoughts))
            raw = thought_compressor.session_thoughts[last_id]
            console.print("\n[#808080]── Thought Block ──[/]")
            console.print(safe_strip(raw) or "(empty)")

    @bindings.add("s-tab")
    def _cycle_modes(event) -> None:
        """Cycle mode: normal → plan mode → accept edits → normal."""
        _cycle_mode()
        event.app.invalidate()  # refresh the bottom toolbar

    def _get_toolbar() -> HTML:
        """Dynamic bottom toolbar: status spinner + phase + token count + mode
        + context warning (Stage 6).

        When idle shows only the mode indicator and shortcuts hint.
        During agent work shows the rotating spinner frame, phase verb,
        and accumulated token count — all updated every 120ms via the
        background ``_toolbar_spinner_loop`` task.

        When accumulated tokens exceed ``_CONTEXT_WARN_THRESHOLD``, a yellow
        warning with ``try /compact`` is appended to the toolbar.
        """
        frame = _STATUS_SPINNER_FRAMES[_STATUS_SPINNER_IDX]
        verb = _STATUS_PHASE_VERBS.get(_status_phase, _STATUS_PHASE_VERBS["idle"])
        token_str = ""
        if _status_tokens > 0:
            if _status_tokens >= 1000:
                token_str = f"  {_status_tokens/1000:.1f}k"
            else:
                token_str = f"  {_status_tokens}"

        # Mode section
        if _mode_state == 1:
            mode_html = '<style bg="ansicyan" fg="black"> plan mode </style>'
        elif _mode_state == 2:
            mode_html = 'accept edits on'
        else:
            mode_html = ''

        # Context warning section (Stage 6 + Stage 8: 150k auto-warning)
        warn_html = ""
        if _status_tokens > 150_000:
            est_k = _status_tokens // 1000
            warn_html = (
                f'  <style bg="yellow" fg="black"> ⚠ {est_k}k tokens </style>'
                '  <style fg="#ff5500">run /compact</style>'
            )
        elif _status_tokens > _CONTEXT_WARN_THRESHOLD:
            est_k = _status_tokens // 1000
            warn_html = (
                f'  <style bg="yellow" fg="black"> ⚠ {est_k}k tokens </style>'
                '  <style fg="#ffaa00">try /compact</style>'
            )

        if _status_phase == "idle":
            # Idle — show mode only, no spinner
            return HTML(
                f'<b>» {mode_html}{warn_html} [shift+tab]  ? for shortcuts</b>'
            )

        return HTML(
            f'<b>{frame} {verb}{token_str}  |  {mode_html}{warn_html} [shift+tab]  ? for shortcuts</b>'
        )

    session = PromptSession(
        style=cyberpunk_style,
        history=FileHistory(HISTORY_FILE),
        key_bindings=bindings,
        bottom_toolbar=_get_toolbar,
        input_processors=[],
    )

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

    # 4. Start consumer task + toolbar spinner task
    consumer_task = asyncio.create_task(render_agent_events(kinetic))
    spinner_task = asyncio.create_task(_toolbar_spinner_loop())

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

                # The top border and the multi-line cyberpunk prompt
                render_todo_block()
                prompt_message = HTML(f"{hr_style}\n<style fg='#00ff9d' bold='true'>╭─ Ammar@NabdOS ~ </style>\n<style fg='#00fff7' bold='true'>╰─❯ </style>")
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

                # ── Stage 8: /compact command ────────────────────────────
                # Intercept BEFORE the agent runs so no LLM call is wasted.
                if text.strip().lower() == "/compact":
                    kinetic.stop()
                    thought_compressor.stop()
                    _handle_compact_command(agent)
                    continue

                # ── Re-entrancy guard ───────────────────────────────────
                # Block the turn if the agent is already busy from a previous
                # turn (shouldn't happen in normal flow, but guards against
                # edge cases like double-keypress or rapid REPL input).
                global _agent_busy
                if _agent_busy:
                    console.print("[yellow]⚠ Agent busy — please wait[/yellow]")
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

                # Inject plan mode instruction into the agent's system prompt
                # when active. We temporarily prepend to the system message so
                # the directive applies at the role level for the entire turn.
                _plan_snapshot: str | None = None
                if _plan_mode:
                    _msgs = getattr(agent, "messages", None) or getattr(
                        getattr(agent, "state", None), "messages", None
                    )
                    if _msgs and len(_msgs) > 0 and _msgs[0].get("role") == "system":
                        _plan_snapshot = _msgs[0]["content"]
                        _msgs[0]["content"] = PLAN_MODE_INSTRUCTION + _plan_snapshot

                # ── Arabic auto-scan: detect "فحر مستودع" etc. and seed ─────
                # the agent's context with a directory listing + evidence
                # before dispatching to the LLM. This ensures the convergence
                # gate sees real file records and the model has concrete paths.
                await asyncio.to_thread(_maybe_auto_scan, text, agent)

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
                    # Restore original system prompt after the turn completes.
                    if _plan_snapshot is not None:
                        _msgs = getattr(agent, "messages", None) or getattr(
                            getattr(agent, "state", None), "messages", None
                        )
                        if _msgs and len(_msgs) > 0:
                            _msgs[0]["content"] = _plan_snapshot
                    # Forcefully kill the spinner after EVERY interaction —
                    # success, failure, or empty-string return (no exception).
                    await bridge.emit_thinking_stop()
                    kinetic.stop()
                    thought_compressor.stop()

                if not (bus_ref and getattr(bus_ref, "_final_answer_rendered", False)) and not (bus_ref and getattr(bus_ref, "_tokens_streamed", False)):
                    clean_resp = extract_clean_answer(response_text)
                    # Last wall (fallback render): strip tool-call JSON lines
                    # from mixed content instead of discarding the whole response.
                    # Only skip rendering when the stripped result is empty
                    # (pure tool call with no user-facing text).
                    if clean_resp:
                        if _ui_looks_like_tool_call(clean_resp):
                            # Mixed content: strip tool-call lines, keep text.
                            stripped = _strip_tool_call_lines(clean_resp)
                            if stripped:
                                clean_resp = stripped
                            else:
                                # Pure tool call with no readable text → skip.
                                clean_resp = ""
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

                # ── Process pending edits (accept-edits mode) ────────────
                # After the agent turn, if accept-edits mode was active and
                # edits were queued, show them and ask for user approval.
                _process_pending_edits()

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
        # Graceful shutdown: stop the streaming consumer + spinner.
        consumer_task.cancel()
        spinner_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        try:
            await spinner_task
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

    def __init__(self, event_bus, state, register_listeners: bool = True):
        self.event_bus = event_bus
        self.state = state
        self.live_context = None
        if self.event_bus:
            self.event_bus._final_answer_rendered = False
        # Single-renderer rule (plan 1.1): only ONE renderer owns stdout. In
        # one-shot / non-interactive mode main.py wires the direct renderer
        # (wire_events) instead, so we must NOT register a second competing
        # renderer here. The caller decides which renderer is active — no
        # runtime flag negotiation between two renderers.
        if register_listeners:
            self._register_listeners()

    def _subscribe_with_fallback(self, event_name, handler):
        """Wrap handler with try/except to prevent subscriber crashes."""
        def safe_handler(data):
            try:
                handler(data)
            except Exception as e:
                try:
                    console.print(
                        Panel(
                            f"[red]Subscriber error for {event_name}: {e}[/red]",
                            title="[bold red]EVENTBUS ERROR[/bold red]",
                            border_style="red"
                        )
                    )
                except Exception:
                    pass
        register_fn = getattr(self.event_bus, "on", None) or getattr(self.event_bus, "subscribe", None)
        if register_fn:
            register_fn(event_name, safe_handler)

    def _register_listeners(self):
        """ربط الأحداث بالدالات البصرية المناسبة لها مع دعم دالتي on و subscribe وتحصين المشتركين ضد الانهيار"""
        if not self.event_bus:
            return
        self.event_bus._on_tool_completed_active = True
        self._subscribe_with_fallback("tool_started", self.on_tool_started)
        self._subscribe_with_fallback("tool_completed", self.on_tool_completed)
        self._subscribe_with_fallback("agent_handoff", self.on_agent_handoff)
        self._subscribe_with_fallback("tool_auth_violation", self.on_tool_auth_violation)
        self._subscribe_with_fallback("show_final_answer", self.on_final_answer)
        # ❌ قم بتعطيل هذا السطر لمنع الواجهة من رسم صناديق فارغة من تلقاء نفسها (الخطوة الأولى: المايسترو الأوحد)
        # self._subscribe_with_fallback("loop_completed", self.on_loop_completed)

    def on_tool_started(self, data: dict):
        """إظهار لوحة بدء الأداة مع سبينر متحرك عند بدء تشغيل أي أداة بناءً على دور الوكيل"""
        try:
            self.stop()  # إيقاف أي سياق عرض نشط أولاً

            role = data.get("role", "ORCHESTRATOR")
            tool_name = data.get("tool") or data.get("tool_name") or "tool"

            # اختيار لون السبينر حسب قبعة الوكيل الحالي
            color = "cyan" if role == "ORCHESTRATOR" else "green" if role == "CODER" else "yellow"

            # لوحة بدء الأداة
            panel = Panel(
                Text(f"Executing: {tool_name} [{role}]", style="neon_cyan"),
                **PANEL_STYLES["tool_start"]
            )
            console.print(panel)

            spinner = Spinner("dots", text=Text(f" [{role}] Running tool: {tool_name}...", style=f"bold {color}"))
            self.live_context = Live(spinner, console=console, refresh_per_second=10, transient=True)
            self.live_context.start()
        except Exception as exc:
            try:
                console.print(f"[dim red][UI] tool spinner unavailable: {exc}[/][/]")
            except Exception:
                pass

    def on_tool_completed(self, data: dict):
        """إيقاف السبينر وطباعة نتيجة الأداة داخل لوحة Panel محصنة"""
        try:
            self.stop()
            tool_name = data.get("tool") or data.get("tool_name") or "?"
            raw_output = data.get("output", "")
            if not raw_output:
                _res = data.get("result")
                if _res is not None:
                    raw_output = (getattr(_res, "output", "") or getattr(_res, "stdout", "")
                                  or getattr(_res, "stderr", ""))

            # Safe string conversion
            output_text = str(raw_output).strip() if raw_output is not None else ""
            if not output_text:
                output_text = "(empty result)"

            # Truncate long outputs
            if len(output_text) > 2000:
                output_text = output_text[:2000] + "\n...[truncated by UI]"

            panel = Panel(
                Text(f"[{tool_name}]\n{output_text}", style="white"),
                **PANEL_STYLES["tool_complete"]
            )
            console.print(panel)
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
        # Last wall: never render a raw tool-call payload as the "answer".
        # If a leaked tool JSON reaches here (despite loop-side hardening),
        # replace it with a clear notice so the FINAL ANSWER card stays clean.
        if _ui_looks_like_tool_call(output):
            output = (
                "⚠️ The agent did not emit a valid final report — it ended on a "
                "tool call instead of `final_answer`. No structured answer was produced."
            )
        if self.event_bus:
            self.event_bus._final_answer_rendered = True

        safe_width = min(console.size.width - 4, 80)

        current_text = ""
        panel = Panel(
            Markdown(current_text),
            border_style="neon_purple",
            box=BOX_FINAL,
            padding=(1, 2),
            width=safe_width,
            title="[bold neon_purple]◆ FINAL ANSWER[/bold neon_purple]",
            subtitle="[dim]Task completed successfully[/dim]",
            subtitle_align="right"
        )

        console.print("\n")

        words = output.split(" ")
        chunk_size = 3

        with Live(panel, console=console, auto_refresh=False) as live:
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                current_text += (" " if current_text else "") + chunk

                panel.renderable = Markdown(current_text)
                live.update(panel, refresh=True)
                time.sleep(0.04)

        console.print("\n")

    def on_loop_completed(self, data: dict):
        """Handle final answer or error from ExecutionLoop with Panel styling and resilience against VerifyError."""
        try:
            self.stop()
            raw_response = data.get(
            "output",
            data.get("response")
        ) if isinstance(data, dict) else data

            # CRITICAL SAFEGUARD: Handle non-string payloads
            if raw_response is None:
                response_text = ""
            elif isinstance(raw_response, Exception):
                exc_type = type(raw_response).__name__
                exc_msg = str(raw_response)
                response_text = f"[{exc_type}] {exc_msg}"
            else:
                response_text = str(raw_response).strip()

            if not response_text:
                response_text = "(session completed — no response)"

            # Choose panel style based on content or exception
            if isinstance(raw_response, Exception) or "ERROR" in response_text.upper() or "EXCEPTION" in response_text.upper() or "VERIFYERROR" in response_text.upper():
                style_key = "error"
            elif "PARTIAL" in response_text.upper():
                style_key = "warning"
            else:
                style_key = "final_answer"

            # If show_final_answer already rendered the answer card, never
            # duplicate it here — regardless of style_key. The FINAL ANSWER
            # card is the single source of the answer; on_loop_completed is a
            # secondary terminal event that must stay silent once it fired.
            if self.event_bus and getattr(self.event_bus, "_final_answer_rendered", False):
                return

            panel = Panel(
                Text(response_text, style="white"),
                **PANEL_STYLES[style_key]
            )
            console.print(panel)
        except Exception as exc:
            try:
                console.print(f"[bold red]✖ on_loop_completed render error: {exc}[/bold red]")
            except Exception:
                pass

    _on_loop_completed = on_loop_completed

    def stop(self):
        """🔒 إغلاق آمن لعرض الـ Live لمنع تعليق الطرفية"""
        if self.live_context:
            try:
                self.live_context.stop()
            except Exception:
                pass
            self.live_context = None


if __name__ == "__main__":
    if "--raw-repl" not in sys.argv:
        print("❌ [SECURITY REJECTION] Direct execution of this module is disabled.")
        print("👉 Please run the system via 'nabdcode' or use '--raw-repl' for maintenance mode.")
        sys.exit(1)

    print("⚠️  [WARNING] Entering Raw Debug REPL. ExecutionLoop guards are BYPASSED.")
    from core.agent_manager import initialize_secure_agent

    asyncio.run(run_repl(agent=initialize_secure_agent()))
