"""D-4 PasteGuard — bracketed-paste protocol owner (separator-driven).

One standalone module owns the whole paste protocol for the REPL:

  - bracketed-paste handshake: send ``\\x1b[?2004h`` on arm and
    ``\\x1b[?2004l`` on every capturable exit path — natural exit,
    exception unwind, SIGINT, SIGTERM, and atexit.  (SIGKILL is not
    capturable by design and is never claimed as covered.)
  - a separator-driven state machine: enter at ``\\x1b[200~``, exit at
    ``\\x1b[201~``.  A timeout is a RECOVERY means only, never a detection
    means.
  - during a paste the whole shortcut layer is bypassed: no key is
    interpreted as a command and no line submits.
  - Shift+Enter is a literal newline, never a submission — both standard
    encodings are supported (``\\x1b[13;2u`` and ``\\x1b[27;2;13~``).

The DEC/ANSI sequences above are generic, standard protocol and are used
freely.  Every symbol in this module is named by this module; no code or
symbol names are reused from any external product.

Declared truncated path (D-4): DISCARD.  If the closing separator never
arrives within the recovery window, the accumulated text is thrown away
and reported TRUNCATED — it is never delivered as if it were complete.

``ui/repl_termux.py`` calls ``arm()`` / ``settle()`` / ``disarm()`` and
contains none of this logic.
"""

from __future__ import annotations

import atexit
import os
import signal
import time
from typing import Optional


class PasteGuard:
    """Bracketed-paste state machine + exit-path hygiene (D-4)."""

    # Standard DEC/ANSI sequences (generic protocol, freely usable).
    ENABLE_SEQ: str = "\x1b[?2004h"       # enable bracketed paste
    DISABLE_SEQ: str = "\x1b[?2004l"      # disable bracketed paste
    START_SEQ: str = "\x1b[200~"          # paste begins (separator)
    END_SEQ: str = "\x1b[201~"            # paste ends (separator)
    SHIFT_ENTER_CSI: str = "\x1b[27;2;13~"   # modified-key encoding
    SHIFT_ENTER_KITTY: str = "\x1b[13;2u"    # kitty-style encoding

    # Recovery window: a timeout is a RECOVERY means only, never detection.
    RECOVERY_SECONDS: float = 2.0

    # feed() decisions.
    SUBMIT: str = "submit"       # a real Enter (never while inside a paste)
    NEWLINE: str = "newline"     # Shift+Enter -> literal newline
    BUFFER: str = "buffer"       # accumulate inside a paste
    COMPLETE: str = "complete"   # paste closed by the \x1b[201~ separator
    TRUNCATED: str = "truncated" # recovery: partial paste discarded
    IGNORE: str = "ignore"       # stray/unsupported byte outside a paste

    def __init__(self, stream=None, *, recovery_seconds: Optional[float] = None):
        self._stream = stream
        self._recovery_seconds = (
            recovery_seconds if recovery_seconds is not None else self.RECOVERY_SECONDS
        )
        self._in_paste: bool = False
        self._buffer: str = ""
        self._completed_text: str = ""
        self._last_activity: float = 0.0
        self._prev_int: object = None
        self._prev_term: object = None
        self._armed: bool = False
        self._handlers_installed: bool = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def arm(self, stream=None, *, install_handlers: bool = True) -> None:
        """Send the enable handshake and install every exit-path handler.

        ``install_handlers=False`` is for pure protocol tests; the REPL
        always arms with the default (handlers installed).
        """
        if stream is not None:
            self._stream = stream
        self._send(self.ENABLE_SEQ)
        # Idempotent: a second arm() must NOT re-register — signal.signal()
        # would return our own first handler as "previous", and _chain()
        # would then recurse into itself on SIGINT/SIGTERM.
        if install_handlers and not self._handlers_installed:
            atexit.register(self.exit_atexit)
            self._prev_int = signal.signal(signal.SIGINT, self.exit_sigint)
            self._prev_term = signal.signal(signal.SIGTERM, self.exit_sigterm)
            self._handlers_installed = True
        self._armed = True

    def disarm(self) -> None:
        """Send the disable handshake.  Idempotent: safe on every exit path."""
        self._send(self.DISABLE_SEQ)

    # ── exit paths (all five capturable ones, each named) ───────────────

    def exit_natural(self) -> None:
        """Natural exit: the REPL loop breaks (exit/quit)."""
        self.disarm()

    def exit_exception(self) -> None:
        """Exception unwind: any error propagates out of the loop."""
        self.disarm()

    def exit_sigint(self, signum, frame) -> None:
        """SIGINT: disable paste, then chain the previous handler."""
        self.disarm()
        self._chain(self._prev_int, signum, frame)

    def exit_sigterm(self, signum, frame) -> None:
        """SIGTERM: disable paste, then chain the previous handler."""
        self.disarm()
        self._chain(self._prev_term, signum, frame)

    def exit_atexit(self) -> None:
        """Interpreter shutdown (backstop for every other path)."""
        self.disarm()

    # ── separator-driven state machine ──────────────────────────────────

    def feed(self, chunk: str) -> list[str]:
        """Consume a raw input chunk; return one decision per unit consumed.

        Inside a paste every byte is buffered (BUFFER): no shortcut, no
        newline, and no submission is ever emitted.  Only the closing
        separator (``\\x1b[201~``) closes the paste as one atomic COMPLETE.
        """
        decisions: list[str] = []
        i = 0
        n = len(chunk)
        while i < n:
            if self._in_paste:
                if chunk.startswith(self.END_SEQ, i):
                    self._in_paste = False
                    self._completed_text = self._buffer
                    self._buffer = ""
                    decisions.append(self.COMPLETE)
                    i += len(self.END_SEQ)
                else:
                    self._buffer += chunk[i]
                    self._last_activity = time.monotonic()
                    decisions.append(self.BUFFER)
                    i += 1
            elif chunk.startswith(self.START_SEQ, i):
                self._in_paste = True
                self._buffer = ""
                self._last_activity = time.monotonic()
                decisions.append(self.IGNORE)
                i += len(self.START_SEQ)
            elif chunk.startswith(self.END_SEQ, i):
                decisions.append(self.IGNORE)  # stray closing marker
                i += len(self.END_SEQ)
            elif chunk.startswith(self.SHIFT_ENTER_CSI, i):
                decisions.append(self.NEWLINE)
                i += len(self.SHIFT_ENTER_CSI)
            elif chunk.startswith(self.SHIFT_ENTER_KITTY, i):
                decisions.append(self.NEWLINE)
                i += len(self.SHIFT_ENTER_KITTY)
            elif chunk[i] in ("\n", "\r"):
                decisions.append(self.SUBMIT)
                i += 1
            else:
                decisions.append(self.IGNORE)
                i += 1
        return decisions

    def begin_paste(self) -> None:
        """Enter the paste state directly (test/API convenience)."""
        self._in_paste = True
        self._buffer = ""
        self._last_activity = time.monotonic()

    def end_paste(self) -> Optional[str]:
        """Close an open paste, returning its buffered text (or None)."""
        if not self._in_paste:
            return None
        self._in_paste = False
        payload = self._buffer
        self._buffer = ""
        return payload

    def is_paste_active(self) -> bool:
        """True while inside a bracketed paste."""
        return self._in_paste

    @property
    def completed_text(self) -> str:
        """The text delivered atomically by the last COMPLETE paste."""
        return self._completed_text

    # ── recovery (a timeout is recovery, never detection) ───────────────

    def is_stale(self) -> bool:
        """True when a paste is still open past the recovery window."""
        if not self._in_paste:
            return False
        return (time.monotonic() - self._last_activity) > self._recovery_seconds

    def recover(self) -> str:
        """Declared D-4 path: DISCARD the partial paste, report TRUNCATED.

        The accumulated text is thrown away and the machine returns to
        idle; it is never delivered as if it were complete.
        """
        if not self._in_paste:
            return ""
        self._buffer = ""
        self._in_paste = False
        self._last_activity = 0.0
        return self.TRUNCATED

    def settle(self, text: str) -> str:
        """REPL seam: decision for a line accepted by the prompt loop.

        If a paste is still open when a line arrives (a broken paste), take
        the declared truncated path (discard) and return an empty string;
        otherwise pass the text through untouched.
        """
        if self._in_paste:
            self.recover()
            return ""
        return text

    # ── internals ────────────────────────────────────────────────────────

    def _send(self, seq: str) -> None:
        if self._stream is None:
            return
        try:
            self._stream.write(seq)
            self._stream.flush()
        except Exception:
            pass

    def _chain(self, previous, signum, frame) -> None:
        """Chain the previously-installed handler — never swallow it."""
        if callable(previous):
            previous(signum, frame)
        elif previous is signal.SIG_IGN:
            return
        else:
            # SIG_DFL: restore the default disposition and re-raise so the
            # process still terminates as intended.
            try:
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
            except Exception:
                pass
