# tools/__init__.py
"""Tools package initialization.

ARCHITECTURAL CONSTRAINT (Phase 3 DI): This __init__.py MUST NOT import any
core/ module at module load time. All core-dependent symbols are either
imported lazily inside factory functions or exposed via Protocol interfaces.

Exports at module level:
  • BaseTool, ToolResult, FileAction — pure tools-layer symbols
  • ShellTool, FileSystemTool, etc. — tool classes (lazy-initialized)
  • Protocol classes from tools.protocols
"""

from __future__ import annotations

from tools.base import BaseTool
from tools.models import ToolResult
from tools.protocols import (
    SecurityEngineProtocol,
    SanitizerProtocol,
    CommandExecutorProtocol,
    PermissionEngineProtocol,
)

# ── Lazy tool accessors ───────────────────────────────────────────────────
# These factory functions ensure core/ modules are ONLY imported when the
# corresponding tool is first constructed or called — never at import time.

def _shell() -> type:
    from tools.shell import ShellTool
    return ShellTool


def _web_search() -> type:
    from tools.web_search import WebSearchTool
    return WebSearchTool


def _file_system() -> type:
    from tools.file_system import FileSystemTool
    return FileSystemTool


def _search_memory() -> type:
    from tools.search_memory import SearchMemoryTool
    return SearchMemoryTool


def _secure_web_search() -> type:
    from tools.secure_tools import SecureWebSearchTool
    return SecureWebSearchTool


def _termux_monitor() -> type:
    from tools.termux_monitor import TermuxMonitorTool
    return TermuxMonitorTool


def _browser() -> type:
    from tools.browser_tool import BrowserTool
    return BrowserTool


def _secure_shell() -> type:
    from tools.secure_tools import SecureShellTool
    return SecureShellTool


# ── Directly importable pure-tools symbols ───────────────────────────────
# These have NO core/ dependency and can be imported eagerly.
from tools.memory import execute_search_memory


# ── Backwards-compatible module-level names (lazy) ───────────────────────
# These resolve at first access, preserving the existing import API
# (``from tools import ShellTool``) while never importing core/ at load time.

def _file_action():
    from tools.file_system import FileAction
    return FileAction


def __getattr__(name: str):
    _lazy_map = {
        "FileAction": _file_action,
        "ShellTool": _shell,
        "WebSearchTool": _web_search,
        "FileSystemTool": _file_system,
        "SearchMemoryTool": _search_memory,
        "SecureWebSearchTool": _secure_web_search,
        "SecureShellTool": _secure_shell,
        "TermuxMonitorTool": _termux_monitor,
        "BrowserTool": _browser,
    }
    if name in _lazy_map:
        return _lazy_map[name]()
    raise AttributeError(f"module 'tools' has no attribute '{name}'")


__all__ = [
    "BaseTool",
    "ToolResult",
    # Protocols
    "SecurityEngineProtocol",
    "SanitizerProtocol",
    "CommandExecutorProtocol",
    "PermissionEngineProtocol",
    # Pure symbols (directly imported above)
    "execute_search_memory",
    # Tools (resolved via __getattr__)
    "FileAction",
    "ShellTool",
    "SecureShellTool",
    "WebSearchTool",
    "SecureWebSearchTool",
    "FileSystemTool",
    "SearchMemoryTool",
    "TermuxMonitorTool",
    "BrowserTool",
]
