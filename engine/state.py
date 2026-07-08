from dataclasses import dataclass, field
from threading import Lock
from typing import List, Dict, Any
from datetime import datetime

# Maximum context size in estimated tokens.
# Uses a simple heuristic: ~4 chars per token for typical English+code text.
# 8192 tokens ≈ 32,768 characters is a safe default for most models.
# The system prompt is always preserved as messages[0].
# Older messages beyond this limit are dropped from index 1 (after system prompt).
MAX_CONTEXT_TOKENS: int = 8192
CHARS_PER_TOKEN: float = 4.0


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: total chars / chars-per-token."""
    return int(len(text) / CHARS_PER_TOKEN)


@dataclass
class RuntimeState:
    """
    Centralized agent runtime state.
    Contains everything the agent needs to resume, trace, and operate.
    """
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)
    session_id: str
    status: str = "INITIALIZED"  # States: RUNNING, PAUSED, ERROR, COMPLETED
    step_count: int = 0
    max_steps: int = 50
    max_context_tokens: int = MAX_CONTEXT_TOKENS
    messages: List[Dict[str, str]] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def get_lock(self) -> Lock:
        """Expose the internal lock for compound operations by the owner."""
        return self._lock

    def update_status(self, new_status: str):
        with self._lock:
            self.status = new_status
            self.last_updated = datetime.utcnow().isoformat()

    def increment_step(self):
        with self._lock:
            self.step_count += 1
            self.last_updated = datetime.utcnow().isoformat()

    def append_message(self, message: Dict[str, str]):
        """Thread-safe message append."""
        with self._lock:
            self.messages.append(message)

    def get_messages(self) -> List[Dict[str, str]]:
        """Thread-safe snapshot of the message list."""
        with self._lock:
            return list(self.messages)

    def set_messages(self, messages: List[Dict[str, str]]):
        """Thread-safe message list replacement."""
        with self._lock:
            self.messages = messages

    def reset_step_count(self):
        """Thread-safe step counter reset."""
        with self._lock:
            self.step_count = 0

    def get_last_message(self) -> Dict[str, str] | None:
        """Thread-safe access to the last message."""
        with self._lock:
            if not self.messages:
                return None
            return dict(self.messages[-1])

    def is_loop_safe(self) -> bool:
        """Prevent infinite execution loops."""
        return self.step_count < self.max_steps

    def prune_history(self):
        """
        Token-aware sliding window: drop oldest messages (after system prompt at index 0)
        until estimated total tokens fit within max_context_tokens.
        """
        with self._lock:
            if len(self.messages) <= 2:
                return

            min_keep = 3
            total_est = sum(
                _estimate_tokens(m.get("content", ""))
                for m in self.messages
            )

            if total_est <= self.max_context_tokens:
                return

            while len(self.messages) > min_keep:
                candidate = [self.messages[0]] + self.messages[2:]
                cand_est = sum(
                    _estimate_tokens(m.get("content", ""))
                    for m in candidate
                )
                if cand_est <= self.max_context_tokens:
                    self.messages = candidate
                    return
                self.messages = candidate

    def to_dict(self) -> dict:
        """Serialize state to a dict for snapshot persistence."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "status": self.status,
                "step_count": self.step_count,
                "messages": list(self.messages),
                "last_updated": self.last_updated,
            }
