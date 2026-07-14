"""core/permissions.py — Session Permission Policy engine (allow/deny/ask).

Grants the operator conditional execution freedom while keeping the
zero-trust architecture intact. A session-scoped ruleset of ``allow`` and
``deny`` rules (exact / glob / regex) is evaluated on every shell command
*before* the interactive 60s prompt is shown.

Cascading trust evaluation (strict, fail-closed):
  1. ADVANCED HEURISTICS (Phase 2.1) — ALWAYS RUN FIRST.
     The obfuscation / exfiltration sweep from core.security
     (``_scan_full_argument_vector`` + dangerous-operator checks) runs on every
     command regardless of any allow rule. A base64 blob, hex-escape smuggling,
     ``eval(``/``exec(`` payload, nested shell, or network-exfil binary is
     BLOCKED even if the user has ``/allow *``. Auto-allow can NEVER weaken
     this layer.
  2. EXPLICIT DENY — any matching deny rule blocks the command.
  3. EXPLICIT ALLOW — any matching allow rule grants it (subject to step 1).
  4. FALLBACK ASK — no rule matched, so the caller shows the interactive
     60s-timeout prompt (the existing behavior).

The ruleset is stored transiently on ``RuntimeState.shell_permissions`` and is
therefore reset on a hard restart (not persisted to disk). The engine itself is
pure and importable without any heavy dependencies.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple

# Phase 2.1 obfuscation / exfiltration sweep — imported lazily to keep this
# module free of a hard import cycle and to guarantee step 1 always runs
# against the canonical checker in core.security.
def _advanced_heuristics_block(command: str) -> Tuple[bool, str]:
    """Run the Phase 2.1 advanced heuristics. Returns (blocked, reason)."""
    from core.security import is_safe_command
    if not is_safe_command(command):
        return True, "blocked by Phase 2.1 advanced heuristics (obfuscation / exfiltration / dangerous operators)"
    return False, ""


class PermissionDecision(Enum):
    """Outcome of a permission evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # no rule matched → fall back to interactive prompt


@dataclass
class PermissionRule:
    """A single allow/deny rule.

    ``pattern`` is matched as:
      • regex  — if it starts and ends with ``/`` (e.g. ``/^git .*/``)
      • glob   — if it contains ``*``, ``?``, or ``[`` (e.g. ``git *``, ``ls -la``)
      • exact  — otherwise (exact full-string match, whitespace-stripped)
    """

    kind: str            # "allow" | "deny"
    pattern: str

    def _compiled(self):
        p = self.pattern.strip()
        if len(p) >= 2 and p.startswith("/") and p.endswith("/"):
            return ("regex", re.compile(p[1:-1]))
        if any(c in p for c in ("*", "?", "[")):
            return ("glob", p)
        return ("exact", p)

    def matches(self, command: str) -> bool:
        cmd = command.strip()
        mode, spec = self._compiled()
        if mode == "regex":
            try:
                return bool(spec.search(cmd))
            except re.error:
                return False
        if mode == "glob":
            return fnmatch.fnmatch(cmd, spec) or fnmatch.fnmatch(cmd, spec.rstrip())
        return cmd == spec


@dataclass
class ShellPermissions:
    """Transient, session-scoped permission ruleset.

    Stored on ``RuntimeState.shell_permissions``; never persisted to disk, so a
    hard restart clears all rules. Order is preserved: rules are evaluated in
    insertion order within each bucket.
    """

    allow: List[PermissionRule] = field(default_factory=list)
    deny: List[PermissionRule] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "ShellPermissions":
        return cls()

    def add_allow(self, pattern: str) -> None:
        self.allow.append(PermissionRule("allow", pattern))

    def add_deny(self, pattern: str) -> None:
        self.deny.append(PermissionRule("deny", pattern))

    def clear(self) -> None:
        self.allow.clear()
        self.deny.clear()

    def to_dict(self) -> dict:
        return {
            "allow": [r.pattern for r in self.allow],
            "deny": [r.pattern for r in self.deny],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShellPermissions":
        sp = cls()
        for p in (data.get("allow") or []):
            sp.add_allow(p)
        for p in (data.get("deny") or []):
            sp.add_deny(p)
        return sp


class PermissionEngine:
    """Evaluates a shell command against the cascading trust hierarchy."""

    @staticmethod
    def evaluate(command: str, perms: ShellPermissions | None) -> Tuple[PermissionDecision, str]:
        """Return (decision, reason) using the strict cascade.

        Hierarchy:
          1. Phase 2.1 advanced heuristics (ALWAYS first, cannot be overridden).
          2. Explicit deny.
          3. Explicit allow.
          4. Fallback ask.
        """
        # 1. ADVANCED HEURISTICS — non-overridable zero-trust floor.
        blocked, reason = _advanced_heuristics_block(command)
        if blocked:
            return PermissionDecision.DENY, reason

        perms = perms or ShellPermissions()

        # 2. EXPLICIT DENY.
        for rule in perms.deny:
            if rule.matches(command):
                return PermissionDecision.DENY, f"matched deny rule: {rule.pattern}"

        # 3. EXPLICIT ALLOW.
        for rule in perms.allow:
            if rule.matches(command):
                return PermissionDecision.ALLOW, f"matched allow rule: {rule.pattern}"

        # 4. FALLBACK ASK.
        return PermissionDecision.ASK, "no rule matched — fall back to interactive prompt"
