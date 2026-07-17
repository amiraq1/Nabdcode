"""core/adapters.py — Adapter bridge between core services and tools Protocols.

Consolidates every Protocol-fulfilling adapter in one file so the wiring
points (agent_manager.py, app_context.py) never define adapter classes
locally.  This eliminates code duplication while keeping the tools layer
decoupled from core/ via the Dependency Inversion seam established in
tools/protocols.py.

Available adapters:

* ``_KernelSecurityEngine``   — wraps ``core.security.validate`` into
                                ``SecurityEngineProtocol``.
* ``_KernelPermissionEngine`` — wraps ``core.permissions.PermissionEngine``
                                into ``PermissionEngineProtocol``.
"""

from __future__ import annotations

from typing import Any, Tuple

from tools.protocols import (
    SecurityEngineProtocol,
    PermissionEngineProtocol,
)


# ── Security Engine Adapter ──────────────────────────────────────────────


class _KernelSecurityEngine(SecurityEngineProtocol):
    """Adapter wrapping ``core.security.validate`` into ``SecurityEngineProtocol``.

    Injected into ``ShellTool`` / ``SecureShellTool`` at construction time
    so the tools layer receives the real kernel security engine directly —
    never the lazy fallback — breaking the circular-import cycle permanently.

    Usage::

        from core.adapters import _KernelSecurityEngine
        shell = SecureShellTool(security_engine=_KernelSecurityEngine())
    """

    __slots__ = ()

    def validate(self, command: str) -> Tuple[bool, str]:
        """Validate *command* against the kernel security policy.

        Returns ``(is_safe: bool, reason: str)``.
        """
        from core.security import validate
        return validate(command)


# ── Permission Engine Adapter ────────────────────────────────────────────


class _KernelPermissionEngine(PermissionEngineProtocol):
    """Adapter wrapping ``core.permissions.PermissionEngine``.

    Provides a clean DI seam so tools and agents never import
    ``core.permissions`` directly — they receive this adapter via their
    constructor and call ``evaluate()``.

    Usage::

        from core.adapters import _KernelPermissionEngine
        from core.permissions import PermissionEngine
        perm = _KernelPermissionEngine(PermissionEngine())
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def evaluate(self, command: str, perms: Any) -> Tuple[Any, str]:
        """Evaluate *command* against the cascading permission rules.

        Returns ``(decision: PermissionDecision, reason: str)``.
        Delegates to ``PermissionEngine.evaluate()``.
        """
        return self._engine.evaluate(command, perms)

    # ── Protocol conformance: PermissionEngineProtocol.check_access ───
    def check_access(self, action: str, resource: str) -> bool:
        """Check whether the agent is authorised for *action* on *resource*.

        Falls back to calling ``evaluate`` and converting the decision
        to a boolean (ALLOW → ``True``, anything else → ``False``).
        """
        from core.permissions import PermissionDecision, ShellPermissions

        decision, _ = self.evaluate(action, ShellPermissions())
        return decision == PermissionDecision.ALLOW
