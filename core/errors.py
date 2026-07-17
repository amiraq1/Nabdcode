# core/errors.py — BRIDGE (Phase 6 DI)
#
# Backward-compatible re-export shim.  The canonical exception taxonomy
# now lives at ``core/kernel/errors.py``.  This file is preserved so
# every existing ``from core.errors import NabdError`` keeps working
# without editing 20+ files in one commit.
#
# NEW CODE should import directly from the canonical module:
#
#   from core.kernel.errors import NabdError
#

from core.kernel.errors import *

__all__ = [
    "NabdError",
    "AuthenticationError",
    "PermissionDeniedError",
    "SandboxExecutionError",
    "MCPConnectionError",
    "MCPToolCallError",
    "StreamTruncationError",
    "TastePipelineError",
    "ConfigurationError",
    "RateLimitExceededError",
    "TelemetryExportError",
]
