# core/kernel/state.py
"""
Centralized agent runtime state — self-contained leaf node.

Zero imports from core/ or engine/. Only imports from sibling kernel modules.
This is the pure canonical home for RuntimeState, GoalSpec, and all
associated helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from .permissions import ShellPermissions


# Maximum context size in estimated tokens.
MAX_CONTEXT_TOKENS: int = 8192

# Phase4 unified token heuristic: ~4 chars per token (code/text blended).
CHARS_PER_TOKEN: float = 4.0


def _estimate_tokens(text: str) -> int:
    """Token estimate using the Phase4 ~4 chars/token heuristic."""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


# ── GoalSpec: objective-driven autonomy ────────────────────────────────────

ACTIVE_GOAL_TAG: str = "active_goal"

_GOAL_PATTERN = re.compile(r'^/goal\s+(.+?)(?:\s*\|\|\s*(.+))?$')
_CRITERIA_FLAG_PATTERN = re.compile(r'^(.+?)\s+-(?:c|criteria)\s+(.+)$')
_MULTILINE_CRITERIA_END = re.compile(r'^--\s*$')


@dataclass
class GoalSpec:
    """A verifiable, objective-driven session goal."""

    raw_prompt: str = ""
    success_criteria: Optional[str] = None
    is_met: bool = False
    description: str = ""
    mode: str = "all"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

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
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
        }

    @staticmethod
    def from_dict(data: dict) -> "GoalSpec":
        if not isinstance(data, dict):
            return GoalSpec()
        crit = data.get("success_criteria")
        created_val = data.get("created_at")
        if isinstance(created_val, str):
            try:
                created_at = datetime.fromisoformat(created_val)
            except Exception:
                created_at = datetime.now(timezone.utc)
        elif isinstance(created_val, datetime):
            created_at = created_val
        else:
            created_at = datetime.now(timezone.utc)
        return GoalSpec(
            raw_prompt=str(data.get("raw_prompt", "")),
            success_criteria=str(crit) if crit is not None and str(crit) != "None" else None,
            is_met=bool(data.get("is_met", False)),
            description=str(data.get("description", "")),
            mode=str(data.get("mode", "all")),
            created_at=created_at,
        )


def build_goal_block(goal: "GoalSpec | None") -> str:
    """Build XML block for system prompt injection."""
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
    """Parse /goal command with multiple formats."""
    stripped = (text or "").strip()
    if not stripped.lower().startswith("/goal"):
        return None

    rest = stripped[len("/goal"):].strip()
    if not rest:
        return None

    # 1. Check multi-line criteria headers
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
    status: str = "INITIALIZED"
    step_count: int = 0
    max_steps: int = 50
    max_context_tokens: int = MAX_CONTEXT_TOKENS
    messages: List[Dict[str, str]] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active_goal: "GoalSpec | None" = None
    shell_permissions: "ShellPermissions" = field(default_factory=ShellPermissions)
    is_fallback_mode_active: bool = False
    provider_fail_streak: int = 0
    past_steps_summary: str = ""
    compacted_memory: List[str] = field(default_factory=list)
    tool_interactions: list = field(default_factory=list)

    def get_lock(self) -> Lock:
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
        with self._lock:
            self.messages.append(message)

    def get_messages(self) -> List[Dict[str, str]]:
        with self._lock:
            return list(self.messages)

    def set_messages(self, messages: List[Dict[str, str]]):
        with self._lock:
            self.messages = messages

    def reset_step_count(self):
        with self._lock:
            self.step_count = 0

    def clear_context(self):
        """Reset conversation messages, memory summaries, tool interactions, step count, and active goal."""
        with self._lock:
            sys_msgs = [m for m in self.messages if m.get("role") == "system"] if self.messages else []
            self.messages = sys_msgs
            self.step_count = 0
            self.past_steps_summary = ""
            self.compacted_memory.clear()
            self.tool_interactions.clear()
            self.active_goal = None
            self.last_updated = datetime.now(timezone.utc).isoformat()

    def get_last_message(self) -> Dict[str, str] | None:
        with self._lock:
            if not self.messages:
                return None
            return dict(self.messages[-1])

    def is_loop_safe(self) -> bool:
        return self.step_count < self.max_steps

    def _active_goal_present(self) -> bool:
        goal = self.active_goal
        if goal is None:
            return False
        crit = getattr(goal, "success_criteria", None)
        return bool(crit) and str(crit) != "None"

    def prune_history(self):
        with self._lock:
            n = len(self.messages)
            min_keep = 2 if self._active_goal_present() else 1
            if n <= min_keep + 1:
                return

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

            max_drop = n - min_keep

            lo, hi = 0, max_drop
            transition = max_drop + 1
            while lo <= hi:
                mid = (lo + hi) // 2
                kept = prefix[min_keep] + (prefix[n] - prefix[mid + min_keep])
                if kept <= self.max_context_tokens:
                    transition = mid
                    hi = mid - 1
                else:
                    lo = mid + 1

            if transition <= max_drop:
                self.messages = self.messages[:min_keep] + self.messages[transition + min_keep:]

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "status": self.status,
                "step_count": self.step_count,
                "messages": list(self.messages),
                "last_updated": self.last_updated,
                "start_time": self.start_time.isoformat() if isinstance(self.start_time, datetime) else str(self.start_time),
            }
