# core/security.py — BRIDGE (Phase 6 DI)
#
# Backward-compatible re-export shim.  The canonical security engine
# now lives at ``core/kernel/security.py``.  This file is preserved so
# every existing ``from core.security import validate`` keeps working
# without editing 20+ files in one commit.
#
# NEW CODE should import directly from the canonical module:
#
#   from core.kernel.security import validate, is_safe_command
#

from core.kernel.security import (  # noqa: F401
    validate,
    is_safe_command,
    split_pipe_segments,
    pin_workspace_root,
    get_workspace_root,
    _validate_path,
    SAFE_BINARIES,
    DANGEROUS_FLAGS,
    INTERPRETERS,
    BANNED_PYTHON_MODULES,
    # Private symbols — re-exported so existing test imports keep working.
    _is_install_command,
    _INSTALL_BLOCKED_MESSAGE,
    _dangerous_operators_unquoted,
    _scan_full_argument_vector,
    _validate_segment_args,
    _tokenize,
)

__all__ = [
    "validate",
    "is_safe_command",
    "split_pipe_segments",
    "pin_workspace_root",
    "get_workspace_root",
    "_validate_path",
    "SAFE_BINARIES",
    "DANGEROUS_FLAGS",
    "INTERPRETERS",
    "BANNED_PYTHON_MODULES",
    "_is_install_command",
    "_INSTALL_BLOCKED_MESSAGE",
    "_dangerous_operators_unquoted",
    "_scan_full_argument_vector",
    "_validate_segment_args",
    "_tokenize",
]
