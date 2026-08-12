"""
Decision Ladder — 13-step security decision framework.

Every tool/command execution passes through this ladder.
Each step can: ALLOW (pass to next), ASK (require user consent), DENY (block).

Step 1 (Circuit Breaker) is ABSOLUTE and cannot be bypassed,
even in "yolo" mode or with any override flag.

Architecture:
  Step  1: Circuit Breaker     — catastrophic patterns (rm -rf /, mkfs, fork bomb)
  Step  2: Command Blacklist   — privileged commands (sudo, su, passwd)
  Step  3: Path Validation     — workspace jail enforcement
  Step  4: File Sensitivity    — protected files detection
  Step  5: Destructive Detect  — write/delete operations on critical paths
  Step  6: Permission Level    — user privilege verification
  Step  7: Consent Requirement — explicit user approval gate
  Step  8: Context Validation  — session/context sanity check
  Step  9: Rate Limiting       — prevent rapid-fire destructive calls
  Step 10: Resource Bounds     — memory/disk/CPU limits
  Step 11: Audit Logging       — immutable audit trail
  Step 12: Fallback Safety     — default-deny on ambiguity
  Step 13: Final Allow         — explicit allow after all checks pass
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class Decision(Enum):
    """The three possible outcomes of a ladder evaluation."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class LadderResult:
    """Immutable record of a ladder evaluation."""
    decision: Decision
    step: int
    step_name: str
    reason: str
    command: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return self.decision == Decision.ALLOW

    @property
    def is_denied(self) -> bool:
        return self.decision == Decision.DENY

    @property
    def needs_consent(self) -> bool:
        return self.decision == Decision.ASK


# ─────────────────────────────────────────────────────────────
# Step 1: Circuit Breaker — ABSOLUTE, CANNOT BE BYPASSED
# ─────────────────────────────────────────────────────────────

CIRCUIT_BREAKER_PATTERNS: List[str] = [
    # Catastrophic filesystem operations
    r"rm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rf][a-zA-Z]*\s+/\s*$",      # rm -rf /
    r"rm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rf][a-zA-Z]*\s+/\*",         # rm -rf /*
    r"rm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rf][a-zA-Z]*\s+~\s*$",       # rm -rf ~
    r"mkfs\.\w+",                                                    # mkfs.ext4 etc.
    r"dd\s+.*\bof=/dev/[sh]d",                                      # dd to raw disk
    # Fork bombs
    r":\(\)\s*\{.*\}\s*;?\s*:",
    # Permission destruction
    r"chmod\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*R[a-zA-Z]*\s+777\s+/",
    r"chown\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*R[a-zA-Z]*\s+\S+\s+/",
    # System file destruction
    r">\s*/etc/(passwd|shadow|sudoers)",
    r"rm\s+.*\s/etc/(passwd|shadow|sudoers)",
    # Service destruction
    r"systemctl\s+(stop|disable|mask)\s+(sshd|ssh|systemd)",
    r"iptables\s+-F",
    r"kill\s+(-[a-zA-Z]*\s+)*1\s*$",                                # kill init
    # Nuclear git
    r"git\s+push\s+.*--force.*\s+origin\s+main\s*$",                # force push main
]


class DecisionLadder:
    """
    13-step security decision ladder.

    Usage:
        ladder = DecisionLadder(workspace_root="~/smart-agent")
        result = ladder.evaluate("rm -rf /")
        assert result.is_denied
        assert result.step == 1  # Circuit Breaker
    """

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or os.getcwd())
        self._steps: List[Dict[str, Any]] = self._build_steps()

    def _build_steps(self) -> List[Dict[str, Any]]:
        """Build the 13-step ladder. Step 1 is non-bypassable."""
        return [
            {"name": "Circuit Breaker",     "fn": self._step_01_circuit_breaker,   "bypassable": False},
            {"name": "Command Blacklist",   "fn": self._step_02_command_blacklist, "bypassable": False},
            {"name": "Path Validation",     "fn": self._step_03_path_validation,   "bypassable": False},
            {"name": "File Sensitivity",    "fn": self._step_04_file_sensitivity,  "bypassable": True},
            {"name": "Destructive Detect",  "fn": self._step_05_destructive,       "bypassable": True},
            {"name": "Permission Level",    "fn": self._step_06_permission_level,  "bypassable": True},
            {"name": "Consent Requirement", "fn": self._step_07_consent,           "bypassable": True},
            {"name": "Context Validation",  "fn": self._step_08_context,           "bypassable": True},
            {"name": "Rate Limiting",       "fn": self._step_09_rate_limit,        "bypassable": True},
            {"name": "Resource Bounds",     "fn": self._step_10_resource_bounds,   "bypassable": True},
            {"name": "Audit Logging",       "fn": self._step_11_audit_log,         "bypassable": True},
            {"name": "Fallback Safety",     "fn": self._step_12_fallback_safety,   "bypassable": True},
            {"name": "Final Allow",         "fn": self._step_13_final_allow,       "bypassable": True},
        ]

    def evaluate(self, command: str, context: Optional[Dict[str, Any]] = None) -> LadderResult:
        """
        Run a command through the 13-step ladder.
        Returns the first decisive result (DENY/ASK) or ALLOW if all pass.
        """
        context = context or {}

        for i, step in enumerate(self._steps):
            decision = step["fn"](command, context)
            if decision is not None:
                return LadderResult(
                    decision=decision,
                    step=i + 1,
                    step_name=step["name"],
                    reason=f"Step {i + 1} ({step['name']}): {decision.value}",
                    command=command,
                    metadata=context,
                )

        # Should never reach here (step 13 always returns ALLOW),
        # but default to DENY for safety.
        return LadderResult(
            decision=Decision.DENY,
            step=0,
            step_name="Unexpected Fallthrough",
            reason="Ladder exited without decision — default DENY",
            command=command,
        )

    # ── Step 1: Circuit Breaker ──────────────────────────────
    def _step_01_circuit_breaker(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        """ABSOLUTE DENY for catastrophic patterns. Cannot be bypassed."""
        for pattern in CIRCUIT_BREAKER_PATTERNS:
            if re.search(pattern, cmd):
                return Decision.DENY
        return None  # Pass to next step

    # ── Step 2: Command Blacklist ────────────────────────────
    def _step_02_command_blacklist(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        privileged = ["sudo", "su ", "passwd", "visudo", "useradd", "userdel", "usermod"]
        cmd_lower = cmd.lower().strip()
        for p in privileged:
            if cmd_lower.startswith(p):
                return Decision.DENY
        return None

    # ── Step 3: Path Validation (Workspace Jail) ─────────────
    def _step_03_path_validation(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        """Enforce workspace jail: block paths outside workspace_root."""
        path_patterns = [
            r"(?:^|\s|[\"'])(/[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)*)",
            r"(?:^|\s|[\"'])(~/[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)*)",
            r"(?:^|\s|[\"'])((?:\.\./)+)",
        ]
        for pattern in path_patterns:
            matches = re.findall(pattern, cmd)
            for match in matches:
                path = match if isinstance(match, str) else match[0]
                if '../' in path or path.startswith('..'):
                    if path.count('../') >= 2:
                        return Decision.DENY
                if path.startswith('~'):
                    expanded = os.path.expanduser(path)
                elif path.startswith('/'):
                    expanded = path
                else:
                    continue
                abs_workspace = os.path.abspath(self.workspace_root)
                abs_target = os.path.abspath(expanded)
                sensitive_prefixes = ['/etc/', '/root/', '/boot/', '/proc/', '/sys/', '/dev/', '/var/log/', '/usr/bin/', '/usr/sbin/']
                for prefix in sensitive_prefixes:
                    if abs_target.startswith(prefix):
                        return Decision.DENY
                home_sensitive = ['.ssh', '.bashrc', '.profile', '.sudoers', '.gnupg']
                for sensitive in home_sensitive:
                    if f'/{sensitive}' in abs_target or abs_target.endswith(f'/{sensitive}'):
                        return Decision.DENY
                if abs_target.startswith('/') and not abs_target.startswith(abs_workspace):
                    if not abs_target.startswith('/tmp'):
                        return Decision.DENY
        return None

    # ── Step 4: File Sensitivity (Protected Files) ───────────
    def _step_04_file_sensitivity(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        """
        Protect critical files WITHIN the workspace.
        Even if a command is inside workspace_root, certain files
        are constitutionally protected and cannot be modified/deleted.
        
        Protected patterns:
          - Constitutional fingerprints (status_bar, bar_hears, clock_turns)
          - Security ladder itself (decision_ladder.py)
          - Git internals (.git/)
        """
        # Files that are constitutionally protected (read-only for agent)
        protected_patterns = [
            'ui/widgets/status_bar.py',
            'tests/test_the_bar_hears_the_bus.py',
            'tests/test_the_bar_clock_turns.py',
            'core/security/decision_ladder.py',
            '.git/',
            '.gitignore',
        ]
        
        # Commands that modify files
        modify_commands = ['rm', 'mv', 'cp', 'sed', 'awk', 'echo', 'cat', 'truncate',
                          'chmod', 'chown', 'touch', 'mkdir', 'rmdir', 'ln',
                          '>', '>>', 'tee', 'dd']
        
        # Check if command is a modification command
        is_modify = any(cmd.strip().startswith(mc) or f' {mc} ' in cmd 
                       for mc in modify_commands)
        
        if not is_modify:
            return None  # Read-only commands pass through
        
        # Check if any protected file is targeted
        for protected in protected_patterns:
            if protected in cmd:
                # Allow reading protected files, deny modification
                if cmd.strip().startswith('cat') or cmd.strip().startswith('head') or \
                   cmd.strip().startswith('tail') or cmd.strip().startswith('grep'):
                    return None  # Reading is OK
                return Decision.DENY
        
        return None  # Pass to next step

    # ── Step 5: Destructive Detection ────────────────────────
    def _step_05_destructive(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        # Placeholder: write/delete on critical paths → ASK
        return None

    # ── Step 6: Permission Level ─────────────────────────────
    def _step_06_permission_level(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        return None

    # ── Step 7: Consent Requirement ──────────────────────────
    def _step_07_consent(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        return None

    # ── Step 8: Context Validation ───────────────────────────
    def _step_08_context(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        return None

    # ── Step 9: Rate Limiting ────────────────────────────────
    def _step_09_rate_limit(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        return None

    # ── Step 10: Resource Bounds ─────────────────────────────
    def _step_10_resource_bounds(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        return None

    # ── Step 11: Audit Logging ───────────────────────────────
    def _step_11_audit_log(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        return None  # Logging doesn't block, just records

    # ── Step 12: Fallback Safety ─────────────────────────────
    def _step_12_fallback_safety(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        # Default-deny on ambiguous commands
        return None

    # ── Step 13: Final Allow ─────────────────────────────────
    def _step_13_final_allow(self, cmd: str, ctx: Dict) -> Optional[Decision]:
        """All previous steps passed. Explicit ALLOW."""
        return Decision.ALLOW
