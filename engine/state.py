from dataclasses import dataclass, field
from threading import Lock
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from core.permissions import ShellPermissions

# Maximum context size in estimated tokens.
# Uses an adaptive heuristic: ~2-3 chars per token for code-heavy text,
# ~5 chars per token for prose/English.
# The system prompt is always preserved as messages[0].
# Older messages beyond this limit are dropped from index 1 (after system prompt).
MAX_CONTEXT_TOKENS: int = 8192

# Phase4 unified token heuristic: ~4 chars per token (code/text blended).
# Replaces the earlier prose/code split so the compaction layer and the
# token-counter spinner agree on a single, predictable estimate.
CHARS_PER_TOKEN: float = 4.0


def _estimate_tokens(text: str) -> int:
    """Token estimate using the Phase4 ~4 chars/token heuristic.

    A single, fast, deterministic estimate used by both pruning and the
    kinetic token counter so every subsystem speaks the same unit.
    """
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


# ── GoalSpec: objective-driven autonomy ────────────────────────────────────
#
# A GoalSpec is the strict, verifiable session objective set via the ``/goal``
# command. The agent must NOT terminate with "Success" unless the Verifier
# explicitly proves every success criterion has been met against live evidence.

@dataclass
class GoalSpec:
    """A verifiable, objective-driven session goal.

    Fields:
      • raw_prompt       — the literal text the operator passed to ``/goal``.
      • success_criteria — the explicit, checkable exit conditions the agent
                           must satisfy before it may halt as "Success".
      • is_met           — set True ONLY by the Verifier once it has proven the
                           criteria against live workspace evidence. Never set
                           by the LLM or any termination path on its own.
      • description      — user description of the goal.
      • mode             — "all" or "any" for multiple criteria.
    """

    raw_prompt: str = ""
    success_criteria: Optional[str] = None
    is_met: bool = False
    description: str = ""
    mode: str = "all"

    def __post_init__(self):
        if not self.description and self.success_criteria:
            self.description = self.raw_prompt
        elif not self.description and self.raw_prompt:
            self.description = self.raw_prompt

    def to_dict(self) -> dict:
        return {
            "raw_prompt": self.raw_prompt,
            "success_criteria": self.success_criteria,
            "is_met": self.is_met,
            "description": self.description,
            "mode": self.mode,
        }

    @staticmethod
    def from_dict(data: dict) -> "GoalSpec":
        if not isinstance(data, dict):
            return GoalSpec()
        crit = data.get("success_criteria")
        return GoalSpec(
            raw_prompt=str(data.get("raw_prompt", "")),
            success_criteria=str(crit) if crit is not None and str(crit) != "None" else None,
            is_met=bool(data.get("is_met", False)),
            description=str(data.get("description", "")),
            mode=str(data.get("mode", "all")),
        )


# XML tag guard used when injecting the active goal into the LLM context. The
# Verifier and loop treat text inside <active_goal> as a hard-preserved
# standing objective that the Phase4 sliding-window compaction must never drop.
ACTIVE_GOAL_TAG: str = "active_goal"


from html import escape
import re

_GOAL_PATTERN = re.compile(r'^/goal\s+(.+?)(?:\s*\|\|\s*(.+))?$')
_CRITERIA_FLAG_PATTERN = re.compile(r'^(.+?)\s+-(?:c|criteria)\s+(.+)$')
_MULTILINE_CRITERIA_END = re.compile(r'^--\s*$')


def build_goal_block(goal: "GoalSpec | None") -> str:
    """Build XML block for system prompt injection"""
    if not goal or not getattr(goal, "raw_prompt", "") or not str(goal.raw_prompt).strip():
        return ""

    intent_str = escape(str(goal.raw_prompt).strip())
    mode_str = getattr(goal, "mode", "all") or "all"
    lines = [f'<active_goal intent="{intent_str}" mode="{mode_str}">']
    if getattr(goal, "success_criteria", None) and str(goal.success_criteria).strip() and str(goal.success_criteria) != "None":
        lines.append(f'<criteria>{escape(str(goal.success_criteria).strip())}</criteria>')
    lines.append('</active_goal>')
    return "\n".join(lines)


def parse_goal_command(text: str) -> "GoalSpec | None":
    """Parse /goal command with multiple formats:
    - /goal <description>
    - /goal <description> || <criteria>
    - /goal <description> -c <criteria>
    - /goal <description> --criteria <criteria>
    - Multiline: /goal <description>
      Criteria:
      - item 1
      - item 2
      --
    """
    stripped = (text or "").strip()
    if not stripped.lower().startswith("/goal"):
        return None

    rest = stripped[len("/goal"):].strip()
    if not rest:
        return None

    # 1. Check multi-line criteria headers ("Criteria:", "Success criteria:", or lone "--")
    lines_match = re.split(
        r'\n\s*(?:(?:success\s+)?criteria\s*:|--)\s*\n?',
        rest,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    if len(lines_match) == 2 and lines_match[1].strip():
        return GoalSpec(
            raw_prompt=lines_match[0].strip(),
            success_criteria=lines_match[1].strip()
        )

    # 2. Check --criteria / -c flag (prefix or suffix)
    m_prefix = re.match(
        r'^(?:--criteria|-c)\s+(?:"([^"]+)"|\'([^\']+)\'|([^\s]+))\s+(.+)$',
        rest,
        flags=re.DOTALL,
    )
    if m_prefix:
        crit = m_prefix.group(1) or m_prefix.group(2) or m_prefix.group(3)
        desc = m_prefix.group(4).strip()
        return GoalSpec(raw_prompt=desc, success_criteria=crit.strip())

    m_suffix = re.search(
        r'^(.*?)\s+(?:--criteria|-c)\s+(?:"([^"]+)"|\'([^\']+)\'|(.+))$',
        rest,
        flags=re.DOTALL,
    )
    if m_suffix and m_suffix.group(1).strip():
        desc = m_suffix.group(1).strip()
        crit = m_suffix.group(2) or m_suffix.group(3) or m_suffix.group(4)
        return GoalSpec(raw_prompt=desc, success_criteria=crit.strip())

    # 3. Check "||" delimiter
    if "||" in rest:
        desc, _, crit = rest.partition("||")
        desc = desc.strip()
        crit = crit.strip()
        return GoalSpec(
            raw_prompt=desc,
            success_criteria=crit if crit else None
        )

    # 4. Simple: /goal desc only
    return GoalSpec(raw_prompt=rest, success_criteria=None)


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
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Phase5 (GoalSpec): the active verifiable session objective, set via the
    # ``/goal`` command. None when the agent is running in ad-hoc mode. The
    # Verifier enforces this before any "Success" termination (see
    # engine.goal_verifier).
    active_goal: "GoalSpec | None" = None
    # Phase5 (Permissions): transient, session-scoped shell allow/deny ruleset.
    # Stored on RuntimeState so the PermissionEngine can read it from the shell
    # gate; intentionally NOT persisted to disk — reset on a hard restart.
    shell_permissions: "ShellPermissions" = field(default_factory=ShellPermissions)

    def get_lock(self) -> Lock:
        """Expose the internal lock for compound operations by the owner."""
        return self._lock

    def update_status(self, new_status: str):
        with self._lock:
            self.status = new_status
            self.last_updated = datetime.now(timezone.utc).isoformat()

    def increment_step(self):
        with self._lock:
            self.step_count += 1
            self.last_updated = datetime.now(timezone.utc).isoformat()

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

    def _active_goal_present(self) -> bool:
        """True when a verifiable GoalSpec with success criteria is active.

        A goal only "counts" once it carries non-empty ``success_criteria``; a
        goal with no criteria is treated as casual/chat. Used by prune_history
        to decide whether the original user prompt (messages[1]) must be
        hard-pinned at the top of the context or may slide out in casual mode.
        """
        goal = self.active_goal
        if goal is None:
            return False
        crit = getattr(goal, "success_criteria", None)
        return bool(crit) and str(crit) != "None"

    def prune_history(self):
        """
        Token-aware sliding window: drop oldest messages (after system prompt at index 0)
        until estimated total tokens fit within max_context_tokens.
        Uses prefix sums + binary search in O(log n) time.
        """
        with self._lock:
            n = len(self.messages)
            # The system prompt (messages[0]) is always hard-preserved. The
            # original user prompt (messages[1]) is ONLY hard-preserved when a
            # verifiable goal is active — see _active_goal_present(). In casual
            # chat mode (no goal) it competes in the sliding window like any
            # other turn, so a stale greeting can never pin the context and
            # displace the latest question.
            min_keep = 2 if self._active_goal_present() else 1
            if n <= min_keep + 1:
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

            max_drop = n - min_keep  # never drop the preserved prefix

            # f(mid) = kept tokens after dropping mid messages starting from
            # index ``min_keep``. Kept: messages[0:min_keep] + messages[mid+min_keep .. n-1].
            # f is monotonically decreasing with mid; we want the SMALLEST mid
            # s.t. f(mid) <= max_context_tokens (keep most history in budget).
            lo, hi = 0, max_drop
            transition = max_drop + 1  # sentinel: no feasible mid found
            while lo <= hi:
                mid = (lo + hi) // 2
                # Kept: messages[0:min_keep] + messages[mid+min_keep .. n-1]
                kept = prefix[min_keep] + (prefix[n] - prefix[mid + min_keep])
                if kept <= self.max_context_tokens:
                    transition = mid
                    hi = mid - 1
                else:
                    lo = mid + 1

            if transition <= max_drop:
                # Drop `transition` messages from index ``min_keep``.
                self.messages = self.messages[:min_keep] + self.messages[transition + min_keep:]

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
