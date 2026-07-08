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

    def emit(self, event_name: str, payload: Any = None):
        """
        Emit an event to all subscribers.
        Example: emit("tool_executed", {"tool": "shell", "status": "success"})
        """
        if event_name in self._subscribers:
            # Use a snapshot of values to avoid concurrent modification
            for callback in list(self._subscribers[event_name].values()):
                try:
                    callback(payload)
                except Exception as e:
                    # Catch errors so one subscriber never crashes the system
                    import sys
                    print(f"[EventBus] subscriber failed for event {event_name}: {e}", file=sys.stderr)

# Singleton instance used by the entire system
bus = EventBus()
