from dataclasses import dataclass, field
from threading import Lock
from typing import List, Dict, Any
from datetime import datetime

# Maximum context size in estimated tokens.
# Uses an adaptive heuristic: ~2-3 chars per token for code-heavy text,
# ~5 chars per token for prose/English.
# The system prompt is always preserved as messages[0].
# Older messages beyond this limit are dropped from index 1 (after system prompt).
MAX_CONTEXT_TOKENS: int = 8192
CHARS_PER_TOKEN_PROSE: float = 5.0
CHARS_PER_TOKEN_CODE: float = 2.5


def _estimate_tokens(text: str) -> int:
    """Adaptive token estimate: code-dense text uses fewer chars/token."""
    if not text:
        return 0
    # Heuristic: count non-whitespace, non-letter chars (signals code density)
    special = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    ratio = special / max(len(text), 1)
    # More special chars = more code-like = denser tokens
    if ratio > 0.3:
        cpt = CHARS_PER_TOKEN_CODE
    else:
        cpt = CHARS_PER_TOKEN_PROSE
    return max(1, int(len(text) / cpt))


@dataclass
class RuntimeState:
    """
    Centralized agent runtime state.
    Contains everything the agent needs to resume, trace, and operate.
    """
    session_id: str
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)
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
        Uses prefix sums + binary search in O(log n) time.
        """
        with self._lock:
            n = len(self.messages)
            if n <= 3:
                return

            # Precompute token estimates and prefix sums
            tokens = [
                _estimate_tokens(m.get("content", ""))
                for m in self.messages
            ]
            prefix = [0] * (n + 1)
            for i in range(n):
                prefix[i + 1] = prefix[i] + tokens[i]

            total = prefix[n]
            if total <= self.max_context_tokens:
                return

            min_keep = 3
            max_drop = n - min_keep

            # f(mid) = kept tokens after dropping mid messages starting from index 1.
            # f is monotonically decreasing with mid (dropping more = fewer tokens).
            # We want the SMALLEST mid s.t. f(mid) <= max_context_tokens
            # (keep the most history while fitting in budget).
            lo, hi = 0, max_drop
            transition = max_drop + 1  # sentinel: no feasible mid found
            while lo <= hi:
                mid = (lo + hi) // 2
                # Kept: messages[0] + messages[mid+1 .. n-1]
                kept = prefix[1] + (prefix[n] - prefix[mid + 1])
                if kept <= self.max_context_tokens:
                    # This mid works. Search left for even smaller mid (keep more history).
                    transition = mid
                    hi = mid - 1
                else:
                    # Too many tokens — need to drop more (larger mid).
                    lo = mid + 1

            if transition <= max_drop:
                # Drop `transition` messages from index 1
                self.messages = [self.messages[0]] + self.messages[transition + 1:]

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
