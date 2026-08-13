# core/kernel/events.py
"""
Central event bus (pub/sub).

Decoupled leaf node — zero imports from core/ or engine/.
The ``EventBus`` singleton is imported by all layers (core, engine, tools, ui)
without creating circular dependencies.
"""

from typing import Callable, Dict, List, Any
from uuid import uuid4


class EventBus:
    """
    Central event bus (pub/sub).
    Decouples all system components via publish-subscribe.
    Returns unsubscribe tokens from subscribe() for clean lifecycle management.
    """
    def __init__(self):
        # Maps event names to subscriber dictionaries {token: callback}
        self._subscribers: Dict[str, Dict[str, Callable]] = {}

    def subscribe(self, event_name: str, callback: Callable) -> Callable:
        """
        Register a callback for an event.
        Returns an unsubscribe callable for clean teardown.
        Idempotent: same callback for same event is not registered twice.
        """
        if event_name not in self._subscribers:
            self._subscribers[event_name] = {}

        # Idempotency: return existing token if callback already registered
        for token, cb in self._subscribers[event_name].items():
            if cb is callback:
                return lambda: self.unsubscribe(event_name, callback)

        token = uuid4().hex[:8]
        self._subscribers[event_name][token] = callback
        return lambda: self._unsubscribe_by_token(event_name, token)

    def _unsubscribe_by_token(self, event_name: str, token: str) -> bool:
        """Remove a subscriber by its token."""
        if event_name in self._subscribers and token in self._subscribers[event_name]:
            del self._subscribers[event_name][token]
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]
            return True
        return False

    def unsubscribe(self, event_name: str, callback: Callable) -> bool:
        """Unregister a callback to prevent listener leaks."""
        if event_name in self._subscribers:
            for token, cb in list(self._subscribers[event_name].items()):
                if cb is callback:
                    del self._subscribers[event_name][token]
                    if not self._subscribers[event_name]:
                        del self._subscribers[event_name]
                    return True
        return False

    def emit(self, event_name: str, payload: Any = None, session_id: str | None = None):
        """
        Emit an event to all subscribers.
        Example: emit("tool_executed", {"tool": "shell", "status": "success"}, session_id="abc")
        """
        if isinstance(payload, dict) and session_id is not None and "session_id" not in payload:
            payload["session_id"] = session_id

        if event_name in self._subscribers:
            # Use a snapshot of values to avoid concurrent modification
            for callback in list(self._subscribers[event_name].values()):
                try:
                    callback(payload)
                except Exception as e:
                    # Catch errors so one subscriber never crashes the system
                    import sys
                    print(f"[EventBus] subscriber failed for event {event_name}: {e}", file=sys.stderr)

        # Bridge to UIBridge if not originating from bridge (avoids loops)
        try:
            if isinstance(payload, dict) and payload.get("_from_bridge"):
                return
            from core.ui_bridge import get_bridge
            bridge = get_bridge()
            if bridge and hasattr(bridge, "_relay_from_bus"):
                bridge._relay_from_bus(event_name, payload)
        except Exception:
            pass


def emit_with_session(
    bus: "EventBus",
    event_name: str,
    payload: Any = None,
    session_id: str | None = None,
) -> None:
    """Emit an event, stamping ``session_id`` into the payload.

    Adds ``session_id`` to the payload dict only when it is not already
    present (``setdefault`` semantics — an emitter that already includes
    its session id is preserved untouched). Non-dict payloads are passed
    through unchanged. This is the single helper for session-tagged
    events; emitters that hold a ``RuntimeState`` (``self.state`` /
    ``self.runtime_state``) pass ``state.session_id`` here. Emitters with
    no state in scope pass nothing — the process-level ``run_id`` is used
    as the fallback session/run id.
    """
    if session_id is None:
        session_id = run_id
    if session_id is not None and isinstance(payload, dict):
        payload.setdefault("session_id", session_id)
    bus.emit(event_name, payload)


# Process-level run id — used as the fallback session/run id for events
# emitted from modules that have no RuntimeState in scope (e.g. the
# subprocess guard, circuit breaker). Kept stable for the process lifetime.
import uuid as _uuid

run_id: str = _uuid.uuid4().hex


# Singleton instance used by the entire system
bus = EventBus()
