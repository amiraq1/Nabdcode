"""D-4 PasteGuard guards — bracketed paste: a separator-driven state machine.

Covers the D-4 acceptance criteria:

  - ``test_paste_with_newline_never_submits`` — a pasted text with at
    least one newline never triggers submission (fails on 4479264, where
    ``ui.repl_termux`` has no paste guard).
  - ``\\x1b[?2004l`` is sent on every capturable exit path — the five by
    name: natural, exception, SIGINT, SIGTERM, atexit.
  - the previous signal handler is chained, never swallowed.
  - both Shift+Enter encodings (``\\x1b[13;2u`` and ``\\x1b[27;2;13~``) are
    a literal newline, never a submission.
  - a truncated paste takes the DECLARED D-4 path (DISCARD): reported
    TRUNCATED, buffer cleared, never delivered as if complete.
"""

from __future__ import annotations

import io
import signal
from unittest.mock import patch

from ui.paste_guard import PasteGuard


def _guarded(buf: io.StringIO) -> PasteGuard:
    """Fresh guard bound to a capture stream, armed WITHOUT process-wide
    handler installation (pure protocol test)."""
    g = PasteGuard(stream=buf)
    g.arm(install_handlers=False)
    return g


# ── never-submit contract ────────────────────────────────────────────────

def test_paste_with_newline_never_submits():
    """A pasted text containing >= 1 newline must never trigger submission:
    every newline inside a bracketed paste is buffered (BUFFER), the paste
    closes with ``\\x1b[201~`` as ONE atomic chunk (COMPLETE), and SUBMIT is
    never emitted.  Fails on 4479264 where ui.repl_termux has no guard."""
    from ui import repl_termux

    guard = repl_termux._paste_guard   # the session-scoped guard the REPL wires
    assert isinstance(guard, PasteGuard)

    events = guard.feed(PasteGuard.START_SEQ + "alpha\nbeta\n" + PasteGuard.END_SEQ)
    assert PasteGuard.SUBMIT not in events
    assert PasteGuard.COMPLETE in events
    assert guard.completed_text == "alpha\nbeta\n"

    # a lone newline while inside a paste is buffered — never a submit
    guard.begin_paste()
    events = guard.feed("gamma\ndelta\n")
    assert PasteGuard.SUBMIT not in events
    assert guard.end_paste() == "gamma\ndelta\n"


def test_paste_buffers_shortcut_sequences_verbatim():
    """During a paste the whole shortcut layer is bypassed: a Shift+Enter
    encoding arriving inside the paste is literal text, not a newline
    command (no key is interpreted as a command during a paste)."""
    g = PasteGuard()
    g.begin_paste()
    events = g.feed(PasteGuard.SHIFT_ENTER_CSI)
    assert events == [PasteGuard.BUFFER] * len(PasteGuard.SHIFT_ENTER_CSI)
    assert PasteGuard.NEWLINE not in events
    assert PasteGuard.SUBMIT not in events
    assert g.end_paste() == PasteGuard.SHIFT_ENTER_CSI


# ── exit paths (five, by name) ───────────────────────────────────────────

def test_disable_seq_emitted_on_all_exit_paths():
    """\\x1b[?2004l must be sent on every capturable exit path — the five
    by name: natural, exception, SIGINT, SIGTERM, atexit."""
    paths = [
        "exit_natural",
        "exit_exception",
        "exit_sigint",
        "exit_sigterm",
        "exit_atexit",
    ]
    for name in paths:
        buf = io.StringIO()
        g = _guarded(buf)
        g._prev_int = lambda *a: None   # chain stubs — never kill the test
        g._prev_term = lambda *a: None
        if name == "exit_sigint":
            args = (signal.SIGINT, None)
        elif name == "exit_sigterm":
            args = (signal.SIGTERM, None)
        else:
            args = ()
        getattr(g, name)(*args)
        assert PasteGuard.DISABLE_SEQ in buf.getvalue(), (
            f"{name} did not emit \\x1b[?2004l"
        )


def test_arm_sends_enable_and_registers_all_handlers():
    """arm() sends \\x1b[?2004h and registers all three exit-handler
    points: the atexit callback plus the SIGINT and SIGTERM handlers."""
    buf = io.StringIO()
    g = PasteGuard(stream=buf)
    seen: dict = {}

    def fake_signal(sig, handler):
        seen[sig] = handler
        return signal.SIG_DFL  # pretend the default disposition was previous

    with patch("ui.paste_guard.signal.signal", side_effect=fake_signal), \
         patch("ui.paste_guard.atexit.register") as atexit_reg:
        g.arm(install_handlers=True)

    assert PasteGuard.ENABLE_SEQ in buf.getvalue()
    assert signal.SIGINT in seen
    assert signal.SIGTERM in seen
    atexit_reg.assert_called_once()


def test_double_arm_never_self_chains():
    """A second arm() must not re-register the handlers: signal.signal()
    would otherwise return our own first handler as "previous" and the
    chain would recurse into itself on SIGINT/SIGTERM."""
    buf = io.StringIO()
    g = PasteGuard(stream=buf)
    seen: dict = {}

    def fake_signal(sig, handler):
        seen.setdefault(sig, []).append(handler)
        return signal.SIG_DFL

    with patch("ui.paste_guard.signal.signal", side_effect=fake_signal), \
         patch("ui.paste_guard.atexit.register") as atexit_reg:
        g.arm(install_handlers=True)
        g.arm(install_handlers=True)

    assert len(seen[signal.SIGINT]) == 1   # registered exactly once
    assert len(seen[signal.SIGTERM]) == 1
    atexit_reg.assert_called_once()


# ── signal chaining ──────────────────────────────────────────────────────

def test_previous_signal_handler_is_chained():
    """The value returned by signal() must be preserved and invoked after
    the disable handshake — never swallowed."""
    buf = io.StringIO()
    calls: list[tuple] = []

    def previous(signum, frame):
        calls.append((signum, frame))

    g = _guarded(buf)
    g._prev_int = previous
    g._prev_term = previous

    g.exit_sigint(signal.SIGINT, None)
    g.exit_sigterm(signal.SIGTERM, None)

    assert PasteGuard.DISABLE_SEQ in buf.getvalue()
    assert len(calls) == 2
    assert calls[0][0] == signal.SIGINT
    assert calls[1][0] == signal.SIGTERM


# ── Shift+Enter: both encodings ──────────────────────────────────────────

def test_shift_enter_both_encodings_are_newline():
    """\\x1b[13;2u and \\x1b[27;2;13~ must both be a literal newline — never
    a submission."""
    for seq in (PasteGuard.SHIFT_ENTER_KITTY, PasteGuard.SHIFT_ENTER_CSI):
        g = PasteGuard()
        events = g.feed(seq)
        assert PasteGuard.NEWLINE in events
        assert PasteGuard.SUBMIT not in events


def test_plain_enter_still_submits_outside_paste():
    """Outside a paste, a real Enter stays a submission — the guard only
    protects pasted newlines, not the Enter key."""
    g = PasteGuard()
    events = g.feed("ls\n")
    assert PasteGuard.SUBMIT in events


# ── truncated path (declared: discard) ───────────────────────────────────

def test_truncated_paste_takes_declared_path():
    """Recovery (timeout) on an unclosed paste must take the DECLARED D-4
    path: DISCARD — TRUNCATED is reported, the buffer is cleared, and the
    partial text is never delivered as if complete."""
    clock = {"t": 100.0}
    with patch("ui.paste_guard.time.monotonic", side_effect=lambda: clock["t"]):
        g = PasteGuard(recovery_seconds=0.001)
        g.begin_paste()
        g.feed("partial line one\npartial line two")
        assert g.is_stale() is False      # inside the recovery window
        clock["t"] = 200.0               # the window expires
        assert g.is_stale() is True
        assert g.recover() == PasteGuard.TRUNCATED
        assert g.is_paste_active() is False
        assert g.completed_text == ""     # nothing delivered as complete
        assert g.end_paste() is None      # no buffer left to hand over


def test_settle_discards_open_paste_not_silent_delivery():
    """The REPL seam: if a line arrives while a paste is still open, the
    declared path is taken (discard, empty string) — never the partial
    text.  Idle lines pass through untouched."""
    g = PasteGuard()
    assert g.settle("ask me something") == "ask me something"
    g.begin_paste()
    g.feed("half of a paste")
    assert g.settle("anything") == ""   # truncated -> discarded
    assert g.is_paste_active() is False
