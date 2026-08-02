"""V-07b: clean display for the raw `scan` / `/deep-scan` JSON body.

The scan command previously printed the repository JSON via bare
``sys.stdout.write``; on narrow Termux screens the terminal wrapped long
path tokens at arbitrary character positions, tearing paths mid-word
(e.g. ``NabdBo`` / ``otloader``).

This module renders the SAME data through Rich with every line
pre-truncated to the panel content width before rendering, and the panel
is printed with ``no_wrap=True`` so Rich can never re-wrap a token at a
character boundary.  Over-long lines are middle-truncated at ``/`` path
separators with an explicit ``…`` marker, keeping the final path segment
(e.g. the filename) visible.

R4 (no fabrication): the preview is computed from the REAL ``data`` dict
passed in; truncation is always marked with ``…``; and the full object is
always recoverable from the caller's ``data`` argument.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

# Safety ceiling: if the pretty-printed JSON exceeds this many console
# screens worth of lines, show a head-preview + instructions instead of
# flooding the scrollback.  Full data stays intact in ``data`` (R4).
_MAX_PREVIEW_SCREENS: int = 3
_HEAD_LINES: int = 20
_ELLIPSIS: str = "…"
_MIN_CONTENT_WIDTH: int = 20


def _content_width(console: Console) -> int:
    """Panel content width = console width minus borders(2) + padding(2)."""
    return max(_MIN_CONTENT_WIDTH, console.width - 4)


def _truncate_line(line: str, max_chars: int) -> str:
    """Middle-truncate *line* to fit *max_chars* without tearing a path.

    Cut points are placed at ``/`` path-separator boundaries whenever
    possible, so no path token is split mid-word; the tail keeps the last
    path segment (filename).  When no boundary exists the cut is still
    explicit and marked with ``…`` — never an unmarked character-level
    wrap.  R4: truncation is display-only and always marked.
    """
    if len(line) <= max_chars:
        return line

    tail = ""
    last_slash = line.rfind("/")
    if last_slash >= 0:
        tail = line[last_slash:]
        if len(tail) >= max_chars - 4:
            tail = ""  # tail too long to be useful; fall through to marker
    if tail:
        head_limit = max_chars - len(_ELLIPSIS) - len(tail)
        head = line[:head_limit]
        cut = head.rfind("/")
        if cut > 0:
            head = head[:cut]
        return head + _ELLIPSIS + tail
    return line[: max_chars - 1] + _ELLIPSIS


def _truncate_body(json_str: str, max_chars: int) -> str:
    """Truncate each line of *json_str* to *max_chars* (marked cuts)."""
    lines = [_truncate_line(ln, max_chars) for ln in json_str.splitlines()]
    return "\n".join(lines)


def render_scan_result(console: Console, data: dict[str, Any]) -> None:
    """Print *data* (a repo-scan dict) cleanly on a narrow terminal.

    * JSON is pretty-printed with ``indent=2`` (same as before).
    * Every line is pre-truncated to the panel content width with marked
      ``…`` cuts at ``/`` boundaries (no mid-word tearing), and the panel
      is printed with ``no_wrap=True`` so Rich cannot re-wrap a token.
    * If the output exceeds ``_MAX_PREVIEW_SCREENS`` screens, only the
      first ``_HEAD_LINES`` lines are shown, followed by an honest
      "N more lines" notice computed from the real line count.

    The *full* JSON is always available to the caller (``data``); only the
    DISPLAY is truncated, never the data.
    """
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    total_lines = json_str.count("\n") + 1
    n_keys = len(data)

    height = max(console.size.height, 1)
    overflow = total_lines > (height * _MAX_PREVIEW_SCREENS)
    cw = _content_width(console)

    if overflow:
        preview_lines = json_str.splitlines()[:_HEAD_LINES]
        preview = _truncate_body("\n".join(preview_lines), cw)
        remaining = total_lines - _HEAD_LINES
        body: Any = Syntax(preview, "json", theme="ansi_dark",
                           word_wrap=False)
        subtitle = f"[dim]… {remaining} more lines (full data preserved)[/]"
        title = f"[bold cyan]📦 Repository scan — {n_keys} top-level keys (preview)[/]"
    else:
        body = Syntax(_truncate_body(json_str, cw), "json", theme="ansi_dark",
                      word_wrap=False)
        subtitle = ""
        title = f"[bold cyan]📦 Repository scan — {n_keys} top-level keys[/]"

    # expand=False → Panel hugs its content width; every content line is
    # already <= content width and no_wrap=True forbids re-wrapping, so no
    # path token can ever tear mid-word, even on a 40-char wide phone.
    panel = Panel(
        body,
        title=title,
        subtitle=subtitle or None,
        expand=False,
        padding=(0, 1),
    )
    console.print()
    console.print(panel, no_wrap=True)
    console.print()
