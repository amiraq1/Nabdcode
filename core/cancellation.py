"""Thread-safe cancellation signal for LLM generation."""

from __future__ import annotations

import threading


class CancelToken:
    """Process-wide singleton signal used to cancel in-flight generation.

    A single shared instance is returned every time ``CancelToken()`` is called,
    so any thread (signal handler, UI keybinding, worker) can raise the flag and
    the streaming loops (``OpenRouterClient.stream`` / ``ExecutionLoop``) read it.
    Backed by a ``threading.Event`` so reads are wait-free and race-safe.
    """

    _instance: "CancelToken | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "CancelToken":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._event = threading.Event()
                    cls._instance._reason = ""
        return cls._instance

    def cancel(self, reason: str = "user") -> None:
        """Raise the cancellation flag with an optional reason string."""
        self._event.set()
        self._reason = reason

    def is_cancelled(self) -> bool:
        """Return True once ``cancel()`` has been called (until ``clear()``)."""
        return self._event.is_set()

    def clear(self) -> None:
        """Lower the flag and reset the reason. Call before every generation."""
        self._event.clear()
        self._reason = ""

    @property
    def reason(self) -> str:
        return self._reason
