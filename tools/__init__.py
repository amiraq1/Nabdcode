# tools/__init__.py
"""
Tools package — full PEP 562 dynamic lazy imports.

ARCHITECTURAL CONSTRAINT (Phase 3 DI + Phase 6 Kernel Island):
This __init__.py MUST NOT import any core/ or tools/ submodule at
module load time.  Every symbol is resolved lazily via __getattr__
(PEP 562), so ``import tools`` or ``from tools import ShellTool``
triggers zero side-effect imports until the specific symbol is
actually accessed.

Usage::

    from tools import ShellTool          # lazy — loads tools.shell
    from tools import BaseTool           # lazy — loads tools.base
    from tools import ToolResult         # lazy — loads tools.models
    from tools import SecureShellTool    # lazy — loads tools.secure_tools
"""

import importlib
from typing import Any, Dict

# ── Lazy mapping: symbol name → relative submodule ────────────────────────
# Only tools/ submodules are referenced here — zero core/ dependencies.
_TOOL_MAPPING: Dict[str, str] = {
    # Base classes & models
    "BaseTool": ".base",
    "ToolResult": ".models",
    "FileAction": ".file_system",
    # Protocols (pure typing, no core/ imports)
    "SecurityEngineProtocol": ".protocols",
    "SanitizerProtocol": ".protocols",
    "CommandExecutorProtocol": ".protocols",
    "PermissionEngineProtocol": ".protocols",
    # Concrete tools
    "ShellTool": ".shell",
    "FileSystemTool": ".file_system",
    "WebSearchTool": ".web_search",
    "SearchMemoryTool": ".search_memory",
    "TodoWriteTool": ".todo",
    "TermuxMonitorTool": ".termux_monitor",
    "BrowserTool": ".browser_tool",
    "GitPushTool": ".git_tool",
    # Secure wrappers
    "SecureTool": ".secure_tools",
    "SecureShellTool": ".secure_tools",
    "SecureFileSystemTool": ".secure_tools",
    "SecureWebSearchTool": ".secure_tools",
    "SecureBrowserTool": ".secure_tools",
    "SecureWorkspaceReader": ".secure_tools",
    "SecureGitInspector": ".secure_tools",
    "SecureTestRunner": ".secure_tools",
    "SecureSemanticMemoryTool": ".secure_tools",
    # Pure function (no core/ dep)
    "execute_search_memory": ".memory",
}


def __getattr__(name: str) -> Any:
    """PEP 562 dynamic lazy import — loads submodule on first access."""
    if name in _TOOL_MAPPING:
        module_path = _TOOL_MAPPING[name]
        module = importlib.import_module(module_path, __package__)
        return getattr(module, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list:
    """Support dir(tools) for IDE discovery."""
    return list(_TOOL_MAPPING.keys())


# For IDE autocomplete and static analysis
__all__ = list(_TOOL_MAPPING.keys())
