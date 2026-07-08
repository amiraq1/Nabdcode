from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime

# Maximum conversation messages kept in context.
# The system prompt is always preserved as messages[0].
# Older messages beyond this limit are dropped from the front (after system prompt).
# Each tool step typically adds 2 messages (assistant + user feedback),
# so 30 messages ≈ 15 tool turns of context.
MAX_CONTEXT_MESSAGES: int = 30


@dataclass
class RuntimeState:
    """
    Centralized agent runtime state.
    Contains everything the agent needs to resume, trace, and operate.
    """
    session_id: str
    status: str = "INITIALIZED"  # States: RUNNING, PAUSED, ERROR, COMPLETED
    step_count: int = 0
    max_steps: int = 50
    messages: List[Dict[str, str]] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def update_status(self, new_status: str):
        self.status = new_status
        self.last_updated = datetime.utcnow().isoformat()

    def increment_step(self):
        self.step_count += 1
        self.last_updated = datetime.utcnow().isoformat()

    def is_loop_safe(self) -> bool:
        """Prevent infinite execution loops."""
        return self.step_count < self.max_steps

    def prune_history(self):
        """
        Sliding window: keep the system prompt (index 0) + last N messages.
        Older messages beyond MAX_CONTEXT_MESSAGES are dropped from index 1.
        """
        if len(self.messages) <= MAX_CONTEXT_MESSAGES + 1:
            return
        # messages[0] is system prompt, always kept
        # drop from index 1 down to len - MAX_CONTEXT_MESSAGES
        keep_from = len(self.messages) - MAX_CONTEXT_MESSAGES
        self.messages = [self.messages[0]] + self.messages[keep_from:]

    def to_dict(self) -> dict:
        """Serialize state to a dict for snapshot persistence."""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "step_count": self.step_count,
            "messages": self.messages,
            "last_updated": self.last_updated
        }
