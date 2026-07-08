from typing import Callable, Dict, List, Any

class EventBus:
    """
    Central event bus (pub/sub).
    Decouples all system components via publish-subscribe.
    """
    def __init__(self):
        # Maps event names to subscriber callback lists
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_name: str, callback: Callable):
        """Register a callback for an event."""
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        if callback not in self._subscribers[event_name]:
            self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable) -> bool:
        """Unregister a callback to prevent listener leaks."""
        if event_name in self._subscribers and callback in self._subscribers[event_name]:
            self._subscribers[event_name].remove(callback)
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
            # Use a copy of the list to avoid concurrent modification issues
            for callback in list(self._subscribers[event_name]):
                try:
                    callback(payload)
                except Exception as e:
                    # Catch errors so one subscriber (e.g. Logger) never crashes the system
                    import sys
                    print(f"[EventBus] subscriber failed for event {event_name}: {e}", file=sys.stderr)

# Singleton instance used by the entire system
bus = EventBus()
