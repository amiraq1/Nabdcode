# core/permissions.py — BRIDGE (Phase 6 DI)
#
# Backward-compatible re-export shim.  The canonical permissions engine
# now lives at ``core/kernel/permissions.py``.  This file is preserved so
# every existing ``from core.permissions import ShellPermissions`` keeps
# working without editing 20+ files in one commit.
#
# NEW CODE should import directly from the canonical module:
#
#   from core.kernel.permissions import ShellPermissions, PermissionEngine
#

from core.kernel.permissions import (  # noqa: F401
    ShellPermissions,
    PermissionEngine,
    PermissionDecision,
    PermissionRule,
)

__all__ = [
    "ShellPermissions",
    "PermissionEngine",
    "PermissionDecision",
    "PermissionRule",
]
