"""Neutral interface contracts for the engine layer.

This module exists purely to break the module-level coupling between
``engine.loop``, ``engine.dispatcher``, ``engine.tool_registry``, and
``core.parser``. By declaring structural ``typing.Protocol`` interfaces here —
with zero imports of those modules — collaborators can annotate their
dependencies against ``engine.interfaces`` instead of importing concrete
classes at module load time.

Runtime dependencies (the dispatcher, the registry) are then injected through
the constructor (Dependency Injection) rather than grabbed from a module-level
singleton, which both removes the import cycle and makes the components
unit-testable in isolation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class ToolResultLike(Protocol):
    """Structural view of ``tools.models.ToolResult`` consumed by the engine."""

    success: bool
    output: str
    returncode: int
    stderr: str


@runtime_checkable
class DispatcherProtocol(Protocol):
    """Anything that can route a tool name + args to execution.

    The concrete ``engine.dispatcher.Dispatcher`` satisfies this, but so does a
    test double — so ``ExecutionLoop``/``NativeDeepAgent`` never need to import
    the concrete class to be constructed or tested.
    """

    def dispatch(
        self, tool_name: str, kwargs: Dict[str, Any], timeout: int = 30
    ) -> ToolResultLike:
        """Execute *tool_name* with *kwargs*, returning a ToolResult-like object."""
        ...


@runtime_checkable
class ToolRegistryProtocol(Protocol):
    """Structural view of ``engine.tool_registry.ToolRegistry``."""

    def get_tool(self, tool_name: str) -> Any:
        """Resolve a registered tool by name."""
        ...

    def __contains__(self, tool_name: str) -> bool:
        """``tool_name in registry`` support."""
        ...

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Return all registered tool schemas."""
        ...


# Sentinel used by callers that want to detect "no dispatcher provided".
UNSET: Any = object()
