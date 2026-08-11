"""ui/cc_style.py — Claude-Code-style rendering primitives.

Pure functions only; no I/O, no event wiring. UI-CC-2 wires these
into TerminalVisualizer.
"""
from __future__ import annotations

import itertools
from typing import Sequence

from ui.design.theme.semantic import SEMANTIC

# BRAND-2: typing-indicator animation frames.
#
# The indicator is "◈ agent" rendered in SEMANTIC.brand (world teal).
# To produce a "pulse" effect we cycle three Rich styles derived from the
# brand color — brand / brand-dim / brand — so the mark breathes without
# embedding any raw #hex in cc_style (the value lives only in the
# SemanticTheme registry).

_brand_style = f"bold {SEMANTIC.brand}"
_brand_dim_style = f"bold {SEMANTIC.brand} dim"


def typing_indicator_frames() -> list["Text"]:
    """Return the list of animation frames for the typing indicator.

    Each frame is a Rich ``Text`` containing "◈ agent" in a brand-derived
    style.  Three frames give a breathing pulse:
    brand → brand-dim → brand.
    """
    from rich.text import Text
    return [
        Text().append("◈ agent", style=_brand_style),
        Text().append("◈ agent", style=_brand_dim_style),
        Text().append("◈ agent", style=_brand_style),
    ]


def typing_indicator_frame(index: int) -> "Text":
    """Return the animation frame at *index* (cycles indefinitely)."""
    frames = typing_indicator_frames()
    return frames[index % len(frames)]

# Badge background routes through the semantic palette (no raw #hex).
BADGE_STYLE = f"bold white on {SEMANTIC.action_badge}"

_STATUS_VERBS = ("Drafting", "Conjuring", "Choreographing",
                 "Abracadabraing", "Crafting")
_verb_cycle = itertools.cycle(_STATUS_VERBS)


def badge_for_tool(tool: str) -> tuple[str, str]:
    """Map a tool name to (LABEL, rich-style) for the badge."""
    t = tool.lower()
    if "read" in t:
        return "READ", BADGE_STYLE
    if any(k in t for k in ("write", "edit", "replace")):
        return "EDIT", BADGE_STYLE
    if "shell" in t:
        return "SHELL", BADGE_STYLE
    if any(k in t for k in ("list", "scan")):
        return "LIST", BADGE_STYLE
    if any(k in t for k in ("search", "web")):
        return "SEARCH", BADGE_STYLE
    if "kill" in t:
        return "KILL", "bold white on red"
    return "TOOL", BADGE_STYLE


def collapse_lines(lines: Sequence[str], keep: int = 3) -> list[str]:
    """Keep first `keep` lines; append a collapse footer if longer."""
    lines = list(lines)
    if len(lines) <= keep:
        return lines
    hidden = len(lines) - keep
    return lines[:keep] + [f"... +{hidden} lines [ctrl+o to expand]"]


def diff_pairs(old: Sequence[str], new: Sequence[str]) -> list[tuple[str, str]]:
    """Line-based diff -> [(sign, text)] with '=', '-', '+'."""
    out: list[tuple[str, str]] = []
    old_set = list(old)
    new_set = list(new)
    for line in old_set:
        if line in new_set:
            out.append(("=", line))
        else:
            out.append(("-", line))
    for line in new_set:
        if line not in old_set:
            out.append(("+", line))
    return out


def todo_line(text: str, done: bool) -> tuple[str, str]:
    """Return (display_text, rich_style) for a todo item."""
    if done:
        return text, "strike green"
    return text, "default"


def format_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def next_status_verb() -> str:
    return next(_verb_cycle)


# ── UI-CC-2: header / thought / status lines ───────────────────────────────

def _primary_arg(args: dict | None) -> str:
    """Pick the primary argument for a tool header line.

    Priority: path, filepath, file, command, query, url; falls back to the
    first string value.  Clamped to 60 characters.
    """
    if not isinstance(args, dict):
        return ""
    for key in ("path", "filepath", "file", "command", "query", "url", "target"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:60]
    for val in args.values():
        if isinstance(val, str) and val.strip():
            return val.strip()[:60]
    return ""


def tool_header_line(tool: str, args: dict | None = None) -> str:
    """Build a Claude-Code-style tool header line: ``BADGE  primary-arg``.

    Returns a plain string like ``READ  main.py``.  The badge label is
    derived from :func:`badge_for_tool`; the argument from
    :func:`_primary_arg`.
    """
    label, _style = badge_for_tool(tool)
    primary = _primary_arg(args)
    if primary:
        return f"{label}  {primary}"
    return label


def thought_line(seconds: int) -> str:
    """Format the thought indicator with an elapsed-seconds count."""
    unit = "second" if seconds == 1 else "seconds"
    return f"✳ Thought for {seconds} {unit} [ctrl+o to expand]"


def status_line(verb: str, tokens: int) -> str:
    """Format a status line with a verb and a human-readable token count."""
    return f"✦ {verb}… {format_tokens(tokens)}"


# ── UI-CC-3: bottom-bar hints + collapse store ──────────────────────────────

def hint_for_mode(mode: str) -> tuple[str, str]:
    """Return (hint_text, rich_style) for the bottom bar given the mode.

    Modes: "plan" (plan mode), "accept" (accept-edits on), "default".
    The style routes through the SEMANTIC palette — no raw #hex.
    """
    if mode == "plan":
        return "plan mode [shift+tab]", f"bold {SEMANTIC.warning}"
    if mode == "accept":
        return "» accept edits on [shift+tab]", f"bold {SEMANTIC.secondary}"
    return "? for shortcuts [shift+tab]", "dim"


class CollapseStore:
    """Store collapsed output blocks by id so they can be expanded later.

    ``store()`` returns an integer id; ``expand(id)`` returns the original
    lines (a fresh list copy) or ``None`` for an unknown/expired id.
    """

    def __init__(self) -> None:
        self._blocks: dict[int, list[str]] = {}
        self._next_id: int = 1

    def store(self, lines: Sequence[str]) -> int:
        """Store *lines* and return its id."""
        cid = self._next_id
        self._next_id += 1
        self._blocks[cid] = list(lines)
        return cid

    def expand(self, cid: int) -> list[str] | None:
        """Return a copy of the stored block, or None if unknown."""
        block = self._blocks.get(cid)
        if block is None:
            return None
        return list(block)

    def ids(self) -> list[int]:
        """Return all stored ids (ascending)."""
        return sorted(self._blocks)


# Process-wide collapse store (UI-CC-3): /expand and future ctrl+o share it.
collapse_store = CollapseStore()


# ── UI-CC-5: compact CC-style lines (no heavy panels) ───────────────────────

def final_answer_header() -> "Text":
    """Build the FINAL ANSWER header line (◆ FINAL ANSWER + light rule).

    Returns a rich ``Text`` (not a Panel) for clean scrollback output.
    """
    from rich.text import Text
    t = Text()
    t.append("◆ FINAL ANSWER", style="bold magenta")
    t.append("\n" + "─" * 40, style="dim")
    return t


def status_compact_line(
    step: int,
    elapsed: float,
    thinking: bool = False,
    tools: bool = False,
    generating: bool = False,
) -> "Text":
    """Build a single-line compact status: ✓/▶/○ phases + step + elapsed.

    Done phases get a green ✓, the active phase a cyan ▶, pending a dim ○.
    Format: ``✓ Thinking ✓ Tools ▶ Generating · Step N · [X.Xs]``
    """
    from rich.text import Text
    t = Text()

    def phase(label: str, done: bool, active: bool) -> None:
        if done:
            t.append("✓ ", style="green")
            t.append(label, style="green")
        elif active:
            t.append("▶ ", style="cyan")
            t.append(label, style="cyan")
        else:
            t.append("○ ", style="dim")
            t.append(label, style="dim")

    # The "active" phase is the first phase that is not yet done, in order.
    active_phase = None
    if not thinking:
        active_phase = "Thinking"
    elif not tools:
        active_phase = "Tools"
    elif not generating:
        active_phase = "Generating"

    phase("Thinking", thinking, active_phase == "Thinking")
    t.append(" ", style="dim")
    phase("Tools", tools, active_phase == "Tools")
    t.append(" ", style="dim")
    phase("Generating", generating, active_phase == "Generating")

    t.append(f" · Step {step}", style="bold")
    t.append(f" · [{elapsed:.1f}s]", style="dim")
    return t


def error_line(msg: str) -> "Text":
    """Build a compact red error line: ``✖ ERROR: <msg>``.

    Returns a rich ``Text`` (not a Panel).
    """
    from rich.text import Text
    t = Text()
    t.append("✖ ERROR: ", style="bold red")
    t.append(str(msg), style="red")
    return t


# ---------------------------------------------------------------------------
# UI-CC-8: compact-line deduplication
# ---------------------------------------------------------------------------

def should_print_compact(last: "str | None", new: str) -> bool:
    """Return True if *new* compact line should be printed.

    Suppresses the line when it is character-for-character identical to the
    previously printed compact line (*last*).  The first call (last=None)
    always returns True.

    Args:
        last: The last compact line that was printed, or None if nothing has
              been printed yet.
        new:  The candidate compact line about to be printed.

    Returns:
        True  → print the line.
        False → suppress (duplicate).
    """
    return last != new

def render_final_answer(text: str):
    """Render the final answer using rich.markdown.Markdown, with safe fallback to rich.text.Text."""
    from rich.markdown import Markdown
    from rich.text import Text
    try:
        return Markdown(text)
    except Exception:
        return Text(text)
