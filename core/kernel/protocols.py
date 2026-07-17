# core/kernel/protocols.py
"""
Abstract protocol contracts for the engine layer.

Zero imports from core/, engine/, or tools/.  These protocols allow the
engine to reference tool-shaped objects without importing concrete tool
classes, breaking the engine ↔ tools circular dependency.

Usage::

    from core.kernel.protocols import ToolCallable

    def dispatch(tool: ToolCallable, kwargs: dict) -> ...:
        result = tool(**kwargs)  # type-safe via Protocol
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class ToolCallable(Protocol):
    """
    Structural protocol representing any invocable tool inside the engine.

    The ToolRegistry and Dispatcher depend ONLY on this contract — they
    never import ``BaseTool`` or any concrete tool class at module load
    time.  This breaks the ``engine → tools → core`` circular edge.
    """

    name: str
    description: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the tool directly for validation and execution."""
        ...

    def get_schema(self) -> Dict[str, Any]:
        """Return the tool's JSON schema for LLM consumption."""
        ...
