"""
renderer — single owner of terminal output.

Architecture
────────────
EventBus (loop thread)
    │
    ▼
Renderer.append() ──→ buffer: list[str]
    │
    ▼ (flush at step boundaries)
Renderer.flush() ──→ sys.stdout.write()

No background threads. No competing writers. No race conditions.
"""

from __future__ import annotations

import shutil
import sys
import textwrap
from typing import Final

CANVAS_WIDTH: Final[int] = 48

SPINNER_FRAMES: Final[tuple[str, ...]] = (
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"
)

TOOL_BADGES: Final[dict[str, tuple[int, int]]] = {
    "execute_shell": (41, 37),   # red bg, white fg
    "file_system":   (42, 37),   # green bg
    "web_search":    (45, 37),   # magenta bg
    "search_memory": (43, 37),   # yellow bg
}


# ── Layout Helpers ──────────────────────────────────────────────────────────

def layout_margin() -> tuple[str, int]:
    """Return (left_margin, effective_width) centered on CANVAS_WIDTH."""
    term_cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    effective = min(term_cols, CANVAS_WIDTH)
    margin = max(0, (term_cols - effective) // 2)
    return " " * margin, effective


def _badge(label: str, bg: int, fg: int = 37) -> str:
    return f"\033[1;{fg};{bg}m {label} \033[0m"


def _tool_badge(tool: str, args: dict) -> str:
    """Return a colored badge for the given tool and action."""
    if tool == "file_system":
        action = str(args.get("action", "")).lower()
        if action in ("read", "list", "exists"):
            return _badge(" READ ", 44)  # blue
        return _badge(" WRITE ", 42)     # green
    bg, fg = TOOL_BADGES.get(tool, (46, 37))  # cyan default
    return _badge(tool.upper()[:6], bg, fg)


# ── Renderer ────────────────────────────────────────────────────────────────

class Renderer:
    """
    Single owner of terminal output.

    Usage (on the loop thread only):
        renderer.print("some line")
        renderer.separator()
        renderer.badge_line("EXEC", "shell", args)
        renderer.flush()

    No background threads. No locks needed — all writes happen on the
    single thread that owns the screen.
    """

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._spinner_idx: int = 0
        self._spinner_active: bool = False

    # ── Buffer Writes ───────────────────────────────────────────────────────

    def print(self, text: str = "") -> None:
        """Append an unformatted line to the buffer."""
        self._lines.append(text)

    def print_margin(self, text: str) -> None:
        """Append a line with left-margin indentation."""
        margin, _ = layout_margin()
        self._lines.append(margin + text)

    def ansi(self, ansi_text: str) -> None:
        """Append a raw ANSI-formatted line."""
        self._lines.append(ansi_text)

    def separator(self) -> None:
        """Append a full-width separator line."""
        margin, w = layout_margin()
        self._lines.append(f"{margin}\033[90m{'─' * w}\033[0m")

    def step_header(self, step: int) -> None:
        """Append a step header: '── [ Step N ] ──'"""
        margin, w = layout_margin()
        label = f"── [ Step {step} ] ──"
        fill = max(0, w - len(label))
        self._lines.append(f"{margin}\033[90m{'─' * fill}{label}\033[0m")

    def badge_line(self, prefix: str, tool: str, args: dict, target: str = "") -> None:
        """Append a badge + tool name + target line."""
        margin, _ = layout_margin()
        badge = _tool_badge(tool, args)
        target_str = f" \033[32m[{target}]\033[0m" if target else ""
        self._lines.append(
            f"{margin}\033[1;37;45m ◆ {prefix} \033[0m {badge}{target_str}"
        )

    def status_line(self, label: str, status_badge: str, detail: str = "") -> None:
        """Append an indented status line: '  └─ OK Code: 0'"""
        margin, _ = layout_margin()
        self._lines.append(f"{margin}  └─ {status_badge} {detail}")

    def text_block(self, lines: list[str]) -> None:
        """Append a block of indented text lines (tool output)."""
        margin, w = layout_margin()
        for line in lines[:10]:
            self._lines.append(f"{margin}\033[90m  │ \033[0m{line[:w-6]}")
        if len(lines) > 10:
            self._lines.append(
                f"{margin}\033[90m  │ ... +{len(lines) - 10} lines [ctrl+o to expand]\033[0m"
            )

    def diff_block(self, diff_text: str) -> None:
        """Append a formatted diff block."""
        margin, _ = layout_margin()
        for line in diff_text.splitlines():
            if line.startswith("---") or line.startswith("+++"):
                self._lines.append(f"{margin}\033[1;36m{line}\033[0m")
            elif line.startswith("@@"):
                self._lines.append(f"{margin}\033[1;33m{line}\033[0m")
            elif line.startswith("-"):
                self._lines.append(f"{margin}\033[1;37;41m{line}\033[0m")
            elif line.startswith("+"):
                self._lines.append(f"{margin}\033[1;37;42m{line}\033[0m")
            else:
                self._lines.append(f"{margin}\033[90m{line}\033[0m")

    def todo_block(self, todos: list[dict]) -> None:
        """Append a formatted todo list."""
        margin, _ = layout_margin()
        self._lines.append(
            f"\n{margin}\033[1;37;45m TODOS \033[0m \033[90m[{len(todos)} items]\033[0m"
        )
        for item in todos:
            done = item.get("done", False)
            text = item.get("task", "")
            if done:
                self._lines.append(f"{margin}  \033[32m☑ \033[9m{text}\033[29m\033[0m")
            else:
                self._lines.append(f"{margin}  \033[37m☐ {text}\033[0m")

    def user_prompt_panel(self, text: str) -> None:
        """Append a user prompt panel (colored background, wrapped)."""
        if not text.strip():
            return
        margin, w = layout_margin()
        wrapper = textwrap.TextWrapper(
            width=max(20, w - 4),
            break_long_words=False,
            break_on_hyphens=False,
            replace_whitespace=True,
        )
        formatted_lines: list[str] = []
        for paragraph in text.splitlines():
            if paragraph.strip() == "":
                formatted_lines.append("")
            else:
                formatted_lines.extend(wrapper.wrap(paragraph))
        bg = "\033[48;5;237m"
        tx = "\033[38;5;253m"
        rst = "\033[0m"
        self._lines.append(f"{rst}")
        for line in formatted_lines:
            padded = f" {line}".ljust(max(1, w - 2))
            self._lines.append(f"{margin}{bg}{tx}{padded}{rst}")
        self._lines.append(f"{rst}")

    def message(self, text: str) -> None:
        """Append a raw message (no formatting, no margin)."""
        self._lines.append(text)

    # ── Spinner ─────────────────────────────────────────────────────────────

    def spinner_start(self) -> None:
        """Mark spinner active. Next flush writes the first frame."""
        self._spinner_active = True
        self._spinner_idx = 0

    def spinner_stop(self) -> None:
        """Deactivate spinner."""
        self._spinner_active = False

    def _spinner_line(self) -> str | None:
        """Return the current spinner line, or None if inactive."""
        if not self._spinner_active:
            return None
        margin, _ = layout_margin()
        frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
        self._spinner_idx += 1
        return (
            f"{margin}\033[1;37;45m {frame} Examining... \033[0m"
            f" \033[90mProcessing context payload...\033[0m"
        )

    # ── Flush ───────────────────────────────────────────────────────────────

    def flush(self) -> None:
        """
        Write all buffered lines + optional spinner to stdout atomically,
        then clear the buffer.

        This is the ONLY function that calls sys.stdout.write or print.
        """
        spinner = self._spinner_line()
        if not self._lines and spinner is None:
            return

        parts: list[str] = []

        if self._lines:
            parts.extend(self._lines)
        if spinner is not None:
            parts.append(spinner)

        sys.stdout.write("\n".join(parts))
        sys.stdout.write("\n")
        sys.stdout.flush()
        self._lines.clear()

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Final flush and terminal cleanup."""
        self.spinner_stop()
        self.flush()
