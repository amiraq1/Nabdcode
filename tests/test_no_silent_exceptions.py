"""tests/test_no_silent_exceptions.py — V5 guard.

Verifies that specific *diagnostic-worthy* exception handlers in
ui/repl_termux.py use logger.debug (or equivalent) instead of bare ``pass``.

Strategy
--------
We check the three call-sites that swallow exceptions which a developer
would want to see during debugging:

1. ``_erase_live_line`` — stdout.flush() failure
2. ``render_agent_events`` — bridge.subscribe failure
3. ``_handle_user_input`` — RepositoryContextManager.update_state (×2)

Handlers that are legitimately silent (teardown, console-print fallbacks,
JSON parsers, asyncio.CancelledError) are explicitly excluded.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path("ui/repl_termux.py")

# ── helpers ────────────────────────────────────────────────────────────────────

def _collect_silent(tree: ast.AST) -> list[int]:
    """Return line numbers of ExceptHandler nodes whose body is only Pass."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.body
        and isinstance(node.body[0], ast.Pass)
    ]


def _context_around(lines: list[str], lineno: int, radius: int = 6) -> str:
    start = max(0, lineno - radius - 1)
    end = min(len(lines), lineno + radius)
    return "\n".join(f"  {i+1}: {lines[i]}" for i in range(start, end))


# ── tests ──────────────────────────────────────────────────────────────────────

def test_bridge_subscribe_is_not_silent() -> None:
    """V5: bridge.subscribe() failure must be logged, not silently swallowed."""
    tree = ast.parse(SRC.read_text())
    lines = SRC.read_text().splitlines()
    silent = _collect_silent(tree)

    # Find exception handlers near bridge.subscribe calls
    for lineno in silent:
        window = "\n".join(lines[max(0, lineno - 8): lineno + 2])
        if "bridge.subscribe" in window:
            ctx = _context_around(lines, lineno)
            raise AssertionError(
                f"bridge.subscribe failure silently swallowed at L{lineno}.\n"
                "Use logger.debug(...) instead of bare pass.\n\n"
                f"Context:\n{ctx}"
            )


def test_repository_context_manager_calls_are_not_silent() -> None:
    """V5: RepositoryContextManager.update_state failures must be logged."""
    tree = ast.parse(SRC.read_text())
    lines = SRC.read_text().splitlines()
    silent = _collect_silent(tree)

    for lineno in silent:
        window = "\n".join(lines[max(0, lineno - 6): lineno + 2])
        if "RepositoryContextManager" in window:
            ctx = _context_around(lines, lineno)
            raise AssertionError(
                f"RepositoryContextManager failure silently swallowed at L{lineno}.\n"
                "Use logger.debug(...) instead of bare pass.\n\n"
                f"Context:\n{ctx}"
            )


def test_stdout_flush_is_not_silent() -> None:
    """V5: stdout.flush() failure in _erase_live_line must be logged."""
    tree = ast.parse(SRC.read_text())
    lines = SRC.read_text().splitlines()
    silent = _collect_silent(tree)

    for lineno in silent:
        window = "\n".join(lines[max(0, lineno - 6): lineno + 2])
        if "sys.stdout.flush" in window or ("stdout" in window and "flush" in window):
            ctx = _context_around(lines, lineno)
            raise AssertionError(
                f"stdout.flush() failure silently swallowed at L{lineno}.\n"
                "Use logger.debug(...) instead of bare pass.\n\n"
                f"Context:\n{ctx}"
            )
