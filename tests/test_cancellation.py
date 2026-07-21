"""Tests for the thread-safe generation CancelToken."""

from __future__ import annotations

import threading

from core.cancellation import CancelToken


def test_singleton_identity() -> None:
    """CancelToken() always returns the same process-wide instance."""
    a = CancelToken()
    b = CancelToken()
    assert a is b


def test_cancel_and_check() -> None:
    """cancel() flips is_cancelled(); reason is captured."""
    tok = CancelToken()
    tok.clear()
    assert tok.is_cancelled() is False
    tok.cancel(reason="user")
    assert tok.is_cancelled() is True
    assert tok.reason == "user"


def test_clear_cycle() -> None:
    """clear() resets the flag so a fresh generation isn't aborted."""
    tok = CancelToken()
    tok.cancel()
    assert tok.is_cancelled() is True
    tok.clear()
    assert tok.is_cancelled() is False
    assert tok.reason == ""


def test_thread_safe_set() -> None:
    """Concurrent cancel()/clear() calls never crash and stay consistent."""
    tok = CancelToken()
    tok.clear()

    def hammer():
        for _ in range(200):
            tok.cancel()
            tok.clear()

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # After racing, the token must still be usable and in a valid state.
    tok.clear()
    assert tok.is_cancelled() is False
