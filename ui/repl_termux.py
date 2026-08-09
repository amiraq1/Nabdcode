# ui/repl_termux.py
"""
Sequential Cyberpunk REPL Mode for Termux (prompt_toolkit + Rich).
100% native Android Soft Keyboard, Copy/Paste, and Readline History support.
"""

from __future__ import annotations

import logging

import asyncio
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import SPINNERS, Spinner
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from core.ui_bridge import get_bridge
from ui.widgets.status_bar import AgentStatusBar
from ui.widgets.tool_result import ToolResultWidget
from ui.widgets.tool_result_list import ToolResultList
from ui.design.theme.semantic import SEMANTIC
from core.context_manager import RepositoryContextManager
from core.permissions import ShellPermissions
from core.kernel.state import RuntimeState
from ui.live_thought import LiveThoughtCompressor
from core.utils import safe_strip
from ui.theme import (
    BOX_EXECUTION,
    BOX_FINAL,
    PANEL_STYLES,
    CUSTOM_THEME,
    PROMPT_HTML_PREFIX,
    PROMPT_HTML_SUFFIX,
    PROMPT_HTML_HR,
)

console = Console(theme=CUSTOM_THEME)

import threading

# V6: _streaming_final guards which tokens reach the final-answer display.
# Written from event handlers (on_llm_request_started, on_final_answer) that
# MAY be called from asyncio.to_thread worker threads, and read by
# _on_token_chunk on the event loop thread.
#
# threading.Event provides explicit, documented thread-safe set()/clear()/is_set()
# semantics (no reliance on CPython GIL atomicity for future compatibility).
_streaming_final: threading.Event = threading.Event()

tool_result_list: ToolResultList = ToolResultList()


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

                # ── Skip synthesized/control markers ──────────────────────────────
        if any(stripped.startswith(p) for p in _SKIP_PREFIXES):
            continue
        if stripped.startswith("Task:") and len(stripped) > 30:
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
        if brace == -1:
            brace = line.rfind('{"output"')
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
    # TODOS badge uses the semantic action-badge color.
    badge_style = _BADGE_STYLES.get("TODOS", f"bold white on {SEMANTIC.action_badge}")
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
#
# Phase 3 (D4): _SESSION_PERMS was a ShellPermissions singleton, now removed.
# _SESSION_PERMS_STATE was a None sentinel for backward-compat; removed in V8.

# ── Mode cycling (Shift+Tab): normal → plan mode → accept edits → normal ──
# 0 = normal, 1 = plan mode, 2 = accept edits
_mode_state: int = 0
_plan_mode: bool = False

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
    """If *text* contains Arabic scan intent, auto-trigger workspace listing.

    V4.4: Evidence seeding and state mutation are delegated to
    core/commands/auto_scan.maybe_auto_scan. This function handles display only.
    """
    from core.commands.auto_scan import maybe_auto_scan as _core_scan

    result = _core_scan(text, agent)
    if not result["triggered"]:
        return False

    if not result["success"]:
        if result.get("error") == "Auto-scan returned empty listing.":
            console.print(f"  [warning]⚠ Auto-scan returned empty listing.[/]")
        else:
            console.print(f"  [error]✗ Auto-scan error: {result.get('error')}[/]")
        return False

    console.print(f"  [success]✓ Auto-scan completed — {result['entry_count']} entries found[/]")
    return True


# ── Context warning threshold (Stage 6) ────────────────────────────────────
# When accumulated tokens exceed this, a warning with "try /compact" appears
# in the bottom toolbar.
_CONTEXT_WARN_THRESHOLD: int = 100_000

# ── Re-entrancy guard — prevents concurrent agent turns ────────────────────
_agent_busy: bool = False

from core.commands.plan_mode import PLAN_MODE_INSTRUCTION  # V4.5: single source of truth


def _cycle_mode() -> None:
    """Cycle through: normal → plan mode → accept edits → normal.

    Mode cycling uses ``set_mode()`` (not ``reset_session()``) so that
    pending edits survive mode transitions.  Only ``/clear`` or session
    landing calls ``reset_session()`` to wipe the queue.
    """
    global _mode_state, _plan_mode
    _mode_state = (_mode_state + 1) % 3
    _plan_mode = (_mode_state == 1)
    # Shared accept-edits state (core/ module — no tools-layer dependency).
    import core.accept_edits_state as _state  # noqa: E402 — lazy
    # set_mode() toggles the flag WITHOUT clearing the pending queue.
    # This ensures pending edits are preserved across mode cycles.
    _state.set_mode(_mode_state == 2)


def _resolve_runtime_state(agent) -> RuntimeState:
    """Best-effort resolve the RuntimeState driving the current agent.

    Prefers the agent's own state (ExecutionLoop.state / NativeDeepAgent.
    runtime_state) so the PermissionEngine reads the exact object the shell
    gate consults. Falls back to a fresh RuntimeState otherwise.
    """
    if agent is not None:
        state = getattr(agent, "state", None) or getattr(agent, "runtime_state", None)
        if isinstance(state, RuntimeState):
            return state
    # Fallback: create a transient RuntimeState for permission evaluation.
    # This is not persisted and does NOT duplicate session state (D4 fix).
    from core.kernel.state import RuntimeState as _RS
    return _RS(session_id="transient-perms", max_steps=5)


def _erase_live_line() -> None:
    """Cleanly clear the single live status row before a full-width print.

    The AgentStatusBar and LiveThought compressor own one terminal
    row written via raw ``sys.stdout``. A ``console.print`` of a Rich
    Panel for a config command (/goal, /skill, /allow) lands on the
    scrollback *under* that live row and can momentarily collide with
    it. Erasing the row first (``\r\033[K``) lets the panel print
    onto a clean line; both writers use the same primitive stdout write.
    """
    try:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
    except Exception as e:  # V5: was bare pass — log for diagnostics
        logger.debug("_erase_live_line: stdout write/flush failed: %s", e)







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
#   READ/EDIT/TODOS/WRITE → action badge teal
#   SHELL → shell orange · SEARCH/EXPLORE/RAG/MEMORY → search purple
#   GIT → git green · KILL → kill red
_BADGE_STYLES: dict[str, str] = {
    "READ":    f"bold white on {SEMANTIC.action_badge}",
    "EDIT":    f"bold white on {SEMANTIC.action_badge}",
    "SHELL":   f"bold black on {SEMANTIC.shell}",
    "SEARCH":  f"bold white on {SEMANTIC.search}",
    "EXPLORE": f"bold white on {SEMANTIC.search}",
    "TODOS":   f"bold white on {SEMANTIC.action_badge}",
    "WRITE":   f"bold white on {SEMANTIC.action_badge}",
    "RAG":     f"bold white on {SEMANTIC.search}",
    "MEMORY":  f"bold white on {SEMANTIC.search}",
    "GIT":     f"bold white on {SEMANTIC.git}",
    "KILL":    f"bold black on {SEMANTIC.kill}",
    "DEFAULT": f"bold white on {SEMANTIC.action_badge}",
}

# ── Prefixes stripped by _strip_tool_call_lines (module-level frozenset) ──
_SKIP_PREFIXES: frozenset[str] = frozenset({
    "[Synthesized answer",
    "[Convergence failed",
    "(Agent stopped",
    "What I found:",
})


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
    fold_hint: str = "",
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
    """Thought content is buffered internally — NEVER printed to the terminal.

    Intermediate reasoning, planning, scratchpad, and chain-of-thought text
    are captured by the LiveThoughtCompressor's internal store (expandable
    via Ctrl+O) but must never reach stdout. This function is intentionally
    a no-op to guarantee that no reasoning leaks to the terminal.
    """
    return


# ── Accept-edits processing ────────────────────────────────────────────────
# Note: Only the `edit` action flows through the pending queue. The `write`,
# `append`, and `replace` actions write immediately regardless of mode.
# This matches the user's spec: accept edits for the `edit` action only.




# Persisted command history (up/down arrows) — survives sessions.
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".nabd_repl_history")


async def render_agent_events(status_bar=None) -> None:
    """Async event consumer rendering agent stream events in Cyberpunk aesthetic.

    Runs for the whole REPL session (one task); survives per-turn 'done'
    sentinels so streaming works across multiple prompts. Cancelled on exit.

    CC reduction (Phase 6.3): the if/elif chain is replaced by a dict dispatch
    mapping event_type -> handler, so each handler has a single responsibility
    and CC <= 5.
    """
    bridge = get_bridge()

    if status_bar is None:
        status_bar = AgentStatusBar(console=console)
        status_bar.wire()

    try:
        def _on_plan_updated(todos):
            _render_todo_from_plan(list(todos) if todos else [])
        bridge.subscribe("on_plan_updated", _on_plan_updated)
    except Exception as e:  # V5: was bare pass — log for diagnostics
        logger.debug("render_agent_events: bridge.subscribe failed: %s", e)

    compressor = thought_compressor
    token_buf = ""
    held_buf = ""
    _stream_line_buf = ""

    # ── Inline flush ──────────────────────────────────────────────────

    def _flush_local_stream() -> None:
        """Print any clean content remaining in the line buffer."""
        nonlocal _stream_line_buf
        if not _stream_line_buf:
            return
        clean = _strip_tool_call_lines(_stream_line_buf)
        if clean:
            _erase_live_line()
            console.print(clean, end="\n", style="white")
        _stream_line_buf = ""

    # ── Event handlers (each handles ONE event type, CC <= 5) ─────────

    def _on_done_event() -> None:
        """Per-turn sentinel — clean up after a completed turn."""
        nonlocal token_buf, held_buf, _stream_line_buf
        if status_bar:
            status_bar.stop()
        _flush_local_stream()
        token_buf = ""
        held_buf = ""
        _stream_line_buf = ""

    def _on_thinking_start() -> None:
        """Begin compressed thought line for a new turn."""
        nonlocal token_buf, held_buf, _stream_line_buf
        compressor.start()
        if status_bar:
            status_bar.start()
        token_buf = ""
        held_buf = ""
        _stream_line_buf = ""
        if hasattr(bridge, "_tokens_streamed"):
            bridge._tokens_streamed = False

    def _on_thinking_stop() -> None:
        """Conclude thought phase, display collapsed reasoning."""
        compressor.stop()
        _display_thought_content(compressor)
        if status_bar:
            status_bar.stop()

    def _on_thought_chunk(content: str) -> None:
        """Accumulate a raw reasoning chunk."""
        compressor.feed(content)

    def _on_tool_start(name: str, args: dict) -> None:
        """Flush stream, stop thought, print action badge."""
        nonlocal token_buf, held_buf, _stream_line_buf
        _flush_local_stream()
        compressor.stop()
        token_buf = ""
        held_buf = ""
        _stream_line_buf = ""
        action, label, meta = _parse_tool_event(name, args or {})
        print_badge(action, label, meta)

    def _on_tool_end(event: dict) -> None:
        """Flush stream, render tool result via ToolResultWidget."""
        _flush_local_stream()
        _other = getattr(bridge, "_on_tool_completed_active", False)
        if not _other:
            tool_name = event.get("tool") or event.get("name") or "?"
            output = safe_strip(event.get("output", ""))
            success = event.get("success", True)
            summary = safe_strip(event.get("summary", ""))
            diff = event.get("diff", "")
            args = event.get("args")
            if output:
                widget = ToolResultWidget(
                    tool_name=tool_name,
                    output=output,
                    success=success,
                    summary=summary,
                    diff=diff,
                    args=args,
                    console=console,
                )
                tool_result_list.add(widget)

    def _on_token_chunk(content: str) -> None:
        """Streaming filter: buffer, strip tool-call lines, display clean.

        Only streams tokens when ``_streaming_final.is_set()`` is True — i.e. when the
        assistant has entered the final-answer phase.  Intermediate reasoning
        and tool-generation tokens are discarded.
        """
        if not _streaming_final.is_set():
            return
        nonlocal token_buf, held_buf, _stream_line_buf
        compressor.add_tokens(len(content))
        token_buf += content
        stripped = token_buf.lstrip()
        if stripped.startswith("{") or stripped.startswith("final_answer"):
            return
        if "final_answer".startswith(stripped):
            held_buf += content
            return
        if held_buf:
            content = held_buf + content
            held_buf = ""
        _stream_line_buf += content
        while "\n" in _stream_line_buf:
            line, _stream_line_buf = _stream_line_buf.split("\n", 1)
            clean_line = _strip_tool_call_lines(line)
            if clean_line:
                compressor.stop()
                if hasattr(bridge, "_tokens_streamed"):
                    bridge._tokens_streamed = True
                _erase_live_line()
                console.print(f"{clean_line}\n", end="", style="white")

    # ── Event dispatch map (CC = 1 flat dict) ─────────────────────────
    _EVENT_DISPATCH = {
        "done":           lambda e: _on_done_event(),
        "thinking_start": lambda e: _on_thinking_start(),
        "thinking_stop":  lambda e: _on_thinking_stop(),
        "thought":        lambda e: _on_thought_chunk(e.get("content", "")),
        "tool_start":     lambda e: _on_tool_start(e.get("name", ""), e.get("args", {})),
        "tool_end":        lambda e: _on_tool_end(e),
        "token":          lambda e: _on_token_chunk(e.get("content", "")),
    }

    try:
        while True:
            compressor.tick()
            event = await bridge.get_event()
            if event is None:
                continue
            handler = _EVENT_DISPATCH.get(event.get("type"))
            if handler is not None:
                handler(event)
    finally:
        compressor.stop()
        if status_bar:
            status_bar.stop()


def _setup_repl_keybindings() -> KeyBindings:
    """Setup Ctrl+O (expand output) and Shift+Tab (cycle mode) bindings.

    Extracted from ``run_repl`` to reduce its cyclomatic complexity.
    Owns only 2 decision points (CC <= 3).
    """
    bindings = KeyBindings()

    @bindings.add("c-o")
    def _on_ctrl_o(event) -> None:
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
            console.print(f"\n[{SEMANTIC.caption}]── Thought Block ──[/]")
            console.print(safe_strip(raw) or "(empty)")

    @bindings.add("s-tab")
    def _cycle_modes(event) -> None:
        """Cycle mode: normal → plan mode → accept edits → normal."""
        _cycle_mode()
        event.app.invalidate()

    return bindings






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
        self._navigation_enabled: bool = False
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
        self._subscribe_with_fallback("llm_request_started", self.on_llm_request_started)
        # ❌ قم بتعطيل هذا السطر لمنع الواجهة من رسم صناديق فارغة من تلقاء نفسها (الخطوة الأولى: المايسترو الأوحد)
        # self._subscribe_with_fallback("loop_completed", self.on_loop_completed)

    def on_llm_request_started(self, data: dict):
        """Reset streaming gate — only final-answer tokens will be streamed."""
        _streaming_final.clear()
        self._navigation_enabled = False
        tool_result_list.clear()

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
                console.print(f"[error][UI] tool spinner unavailable: {exc}[/][/]")
            except Exception:
                pass

    def on_tool_completed(self, data: dict):
        """إيقاف السبينر وطباعة نتيجة الأداة عبر ToolResultWidget"""
        try:
            self.stop()
            tool_name = data.get("tool") or data.get("tool_name") or "?"
            raw_output = data.get("output", "")
            if not raw_output:
                _res = data.get("result")
                if _res is not None:
                    raw_output = (getattr(_res, "output", "") or getattr(_res, "stdout", "")
                                  or getattr(_res, "stderr", ""))

            output_text = str(raw_output).strip() if raw_output is not None else ""
            success = data.get("success", True)
            summary = data.get("summary", "")
            diff = data.get("diff", "")
            args = data.get("args")

            widget = ToolResultWidget(
                tool_name=tool_name,
                output=output_text,
                success=success,
                summary=summary,
                diff=diff,
                args=args,
                console=console,
            )
            tool_result_list.add(widget)
        except Exception as exc:
            try:
                console.print(f"[error][UI] tool completion render failed: {exc}[/][/]")
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
        # Additional safeguard: strip any residual tool-call JSON lines or
        # reasoning markers that may have survived extract_clean_answer.
        output = _strip_tool_call_lines(output)
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

        # Enable token streaming — the assistant has entered the final-answer
        # phase.  Any llm_token events emitted from this point forward will be
        # streamed; earlier intermediate reasoning / tool-generation tokens
        # were discarded by the _streaming_final gate in _on_token_chunk.
        _streaming_final.set()
        self._navigation_enabled = True

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
        chunk_size = 10  # V3: was 3 — 10 words/update × 0.01s = <1s for 600w (was ~8s)

        with Live(panel, console=console, auto_refresh=False) as live:
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                current_text += (" " if current_text else "") + chunk

                panel.renderable = Markdown(current_text)
                live.update(panel, refresh=True)
                time.sleep(0.01)  # V3: was 0.04 — reduced alongside chunk_size increase

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

            # Strip any raw tool-call JSON or reasoning lines from the response
            # before rendering. Only clean, user-facing text may reach the panel.
            response_text = extract_clean_answer(response_text)
            response_text = _strip_tool_call_lines(response_text)
            if not response_text:
                return

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
            console.print()  # A.3: Fix missing newline before next prompt
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


