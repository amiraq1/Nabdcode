"""tests/test_thread_safety.py — V6 guard.

Verifies that _streaming_final in ui/repl_termux.py is marked as
thread-safe (via a threading.Event or threading.Lock usage) OR is
explicitly documented as GIL-safe.

Background
----------
_streaming_final is written by event handlers (on_llm_request_started,
on_final_answer) which may be called from a worker thread via asyncio.to_thread,
and read by _on_token_chunk running on the event loop thread.

In CPython, simple bool reads/writes are GIL-protected (atomic), so the
current implementation is actually safe in practice. However, the code
should be documented to prevent future regressions when/if GIL is removed
(PEP 703).

This guard verifies one of two acceptable states:
1. _streaming_final uses threading.Event (preferred: explicit thread safety)
2. _streaming_final is a plain bool WITH a # noqa-threadsafe or similar comment

Strategy: check that either threading.Event is used, OR that the variable
declaration has a thread-safety comment. If neither, the guard passes with
a note (since GIL makes it safe in practice for CPython 3.x).
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path("ui/repl_termux.py")


def test_streaming_final_thread_safety_is_documented_or_enforced() -> None:
    """V6: _streaming_final thread safety must be either documented or enforced.

    Acceptable states:
    1. Uses threading.Event (best practice)
    2. Has a GIL-safety comment on the declaration line
    3. The variable is only written on the event loop (not from worker threads)

    This test checks option 2: the declaration line must have a thread-safety
    annotation comment OR the file must import threading.
    """
    source = SRC.read_text(encoding="utf-8")
    lines = source.splitlines()

    # Find the _streaming_final declaration line
    decl_line = None
    for i, line in enumerate(lines, 1):
        if "_streaming_final" in line and ("bool" in line or "False" in line or "True" in line or "Event" in line):
            # Check if it's a module-level assignment (not inside a function)
            stripped = line.strip()
            if stripped.startswith("_streaming_final"):
                decl_line = (i, line)
                break

    assert decl_line is not None, (
        "_streaming_final declaration not found in ui/repl_termux.py"
    )

    # Check for threading.Event usage
    uses_threading_event = "threading.Event" in source and "_streaming_final" in source

    # Check for GIL-safety comment on declaration line
    has_gil_comment = any(
        kw in decl_line[1]
        for kw in ("GIL", "thread-safe", "threadsafe", "atomic", "gil_safe", "V6")
    )

    # Check if threading is imported at all
    imports_threading = "import threading" in source

    if uses_threading_event:
        # Best practice: explicit thread safety
        return  # pass

    if has_gil_comment or imports_threading:
        # Documented awareness of thread safety
        return  # pass

    # Neither — add a V6 comment to the declaration line
    # This is a soft failure: we mark it as needing documentation
    raise AssertionError(
        f"V6: _streaming_final at L{decl_line[0]} lacks thread-safety documentation.\n"
        "Add a comment like: # V6: GIL-safe for CPython bool reads/writes\n"
        "Or upgrade to threading.Event for explicit thread safety.\n"
        f"Current line: {decl_line[1].strip()}"
    )
