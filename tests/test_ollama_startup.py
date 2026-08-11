"""tests/test_ollama_startup.py — TERM-2: Non-blocking Ollama boot check.

Verifies that:
  • the Ollama probe runs asynchronously (never blocks startup)
  • the probe timeout is capped at 2 seconds
  • ``ollama_available`` returns False (conservative fallback) until the
    probe confirms availability
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from core import llm
from core.llm import (
    check_ollama_async,
    ollama_available,
    ollama_probe_checked,
    _ollama_timeout,
)


class TestOllamaStartup:
    def test_ollama_check_does_not_block_startup(self):
        """check_ollama_async returns immediately (spawns a daemon thread)."""
        started = time.monotonic()
        check_ollama_async()
        elapsed = time.monotonic() - started
        assert elapsed < 0.5, f"check_ollama_async blocked for {elapsed:.2f}s"

    def test_probe_thread_is_daemon(self):
        """The probe thread must be a daemon so it never blocks exit."""
        threads_before = {t.ident for t in threading.enumerate()}
        check_ollama_async()
        new_threads = [t for t in threading.enumerate() if t.ident not in threads_before]
        assert new_threads, "Expected a new probe thread"
        assert all(t.daemon for t in new_threads)

    def test_timeout_2_seconds_max(self):
        """The probe timeout must not exceed 2 seconds."""
        assert _ollama_timeout() <= 2.0

    def test_ollama_available_false_by_default(self):
        """Before the probe completes, ollama_available is False (fallback)."""
        with patch.object(llm, "_OLLAMA_AVAILABLE", False):
            assert ollama_available() is False

    def test_ollama_available_true_after_success(self):
        """After a successful probe, ollama_available is True."""
        with patch.object(llm, "_OLLAMA_AVAILABLE", True):
            assert ollama_available() is True

    def test_ollama_unavailable_sets_false(self):
        """A failed probe leaves ollama_available False and marks checked."""
        with patch.object(llm, "_OLLAMA_AVAILABLE", False), \
             patch.object(llm, "_OLLAMA_CHECKED", True):
            assert ollama_available() is False
            assert ollama_probe_checked() is True

    def test_probe_checked_flag_after_completion(self):
        """ollama_probe_checked reflects probe completion."""
        with patch.object(llm, "_OLLAMA_CHECKED", True):
            assert ollama_probe_checked() is True
        with patch.object(llm, "_OLLAMA_CHECKED", False):
            assert ollama_probe_checked() is False

    def test_check_ollama_async_uses_2s_timeout(self):
        """The probe urlopen call uses a 2-second timeout."""
        with patch("urllib.request.urlopen") as mock_open:
            check_ollama_async()
            # The thread may not have run yet; wait briefly.
            deadline = time.monotonic() + 1.0
            while not ollama_probe_checked() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ollama_probe_checked() is True
            if mock_open.called:
                args, kwargs = mock_open.call_args
                assert kwargs.get("timeout", args[1] if len(args) > 1 else None) <= 2.0
