"""Live Rich word-diff renderer for the REPL edit-accept flow (V-02).

Modular home for word-level diff rendering. Moved OUT of ``ui/repl_termux.py``
(the ~2000-line god file) per R4: new logic lives here, and the god file only
keeps a one-line call site.

This module is **Rich/ANSI compatible** — it emits Rich-markup strings for the
live ``prompt_toolkit + Rich`` path. It intentionally does **NOT** import
``textual`` (which stays confined to the orphan / deferred Textual UI tree).

V-02 guarantees added over the old inline loop:
  * minimum-match threshold — a changed word-run is highlighted only when it is
    a real (non-trivial) change; runs shorter than ``min_match_len`` chars are
    emitted plain, so markup never fragments on noise.
  * scatter detection — when word-level matching fragments a line into multiple
    interleaved change islands beyond ``scatter_limit``, it falls back to a
    clean whole-line diff, so high-churn edits stay readable.
  * alignment kept — equal (unchanged) tokens are emitted verbatim with **no**
    markup, and markup is never wrapped around an empty string, so column
    alignment survives on narrow-screen wrap.
"""

from __future__ import annotations

import difflib
from typing import Sequence

# V-02 tunables (kept module-level for testability; callers may override).
_DEFAULT_MIN_MATCH_LEN: int = 3      # highlight word-runs >= this many chars
_DEFAULT_SCATTER_LIMIT: float = 0.55  # changed-token fraction that triggers fallback


def _is_add(line: str) -> bool:
    return line.startswith("+") and not line.startswith("+++")


def _is_del(line: str) -> bool:
    return line.startswith("-") and not line.startswith("---")


def _tokens(line: str) -> list[str]:
    return line.split()


def _is_scattered(
    old_toks: Sequence[str],
    new_toks: Sequence[str],
    scatter_limit: float,
) -> bool:
    """True when word matching fragments the line into scattered change islands.

    A line is "scattered" only when it has >= 2 separate change islands AND the
    fraction of changed tokens is above ``scatter_limit``. A single isolated
    change (islands == 1) is not scattered — word-diff stays intact for simple
    edits.
    """
    sm = difflib.SequenceMatcher(None, old_toks, new_toks, autojunk=False)
    islands = 0
    changed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            islands += 1
            changed += (i2 - i1) + (j2 - j1)
    total = len(old_toks) + len(new_toks)
    if total == 0:
        return True
    return islands >= 2 and (changed / total) > scatter_limit


def _word_highlight(old_line: str, new_line: str, min_match_len: int) -> tuple[str, str]:
    """Word-level Rich highlight with a minimum-match threshold.

    Equal tokens are emitted verbatim (plain) to preserve alignment. Changed
    runs are wrapped in Rich red/green spans only when the run is at least
    ``min_match_len`` chars — otherwise emitted plain. Never emits empty markup.
    """
    old_toks = _tokens(old_line)
    new_toks = _tokens(new_line)
    sm = difflib.SequenceMatcher(None, old_toks, new_toks, autojunk=False)

    old_parts: list[str] = []
    new_parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        old_run = " ".join(old_toks[i1:i2])
        new_run = " ".join(new_toks[j1:j2])
        if tag == "equal":
            old_parts.append(old_run)
            new_parts.append(new_run)
            continue
        if old_run and len(old_run) >= min_match_len:
            old_parts.append(f"[bold red]{old_run}[/bold red]")
        elif old_run:
            old_parts.append(old_run)
        if tag in ("replace", "insert"):
            if new_run and len(new_run) >= min_match_len:
                new_parts.append(f"[bold green]{new_run}[/bold green]")
            elif new_run:
                new_parts.append(new_run)
            else:
                new_parts.append("")
    return " ".join(old_parts), " ".join(new_parts)


def render_edit_diff(
    diff_text: str,
    *,
    min_match_len: int = _DEFAULT_MIN_MATCH_LEN,
    scatter_limit: float = _DEFAULT_SCATTER_LIMIT,
) -> str:
    """Render a unified diff as newline-joined Rich-markup lines (for the live REPL).

    Mirrors the former inline loop in ``ui/repl_termux.py`` but adds the
    minimum-match threshold and the automatic line-diff scatter fallback.
    Returns ``""`` for empty input.
    """
    if not diff_text:
        return ""
    lines = diff_text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _is_del(line) and i + 1 < n and _is_add(lines[i + 1]):
            old_line = line[1:].rstrip("\n")
            new_line = lines[i + 1][1:].rstrip("\n")
            old_toks = _tokens(old_line)
            new_toks = _tokens(new_line)
            if _is_scattered(old_toks, new_toks, scatter_limit):
                # Word matching scattered too badly -> clean whole-line diff.
                out.append(f"[red]{line}[/red]")
                out.append(f"[green]{lines[i + 1]}[/green]")
            else:
                hl_old, hl_new = _word_highlight(old_line, new_line, min_match_len)
                out.append(f"[red]-{hl_old}[/red]")
                out.append(f"[green]+{hl_new}[/green]")
            i += 2
        elif _is_add(line):
            out.append(f"[green]{line}[/green]")
            i += 1
        elif _is_del(line):
            out.append(f"[red]{line}[/red]")
            i += 1
        else:
            out.append(f"[dim]{line}[/dim]")
            i += 1
    return "\n".join(out)
