"""Dynamic Adapter: bridges pure BaseSkill objects to the engine's Tool API.

This is the ONLY module allowed to know about both ``skills`` and ``smolagents``.
Keeping the adapter here preserves total decoupling: skills/ stays engine-agnostic,
and swapping the engine means editing only this file.

It also owns the MCP (Model Context Protocol) injection: the adapter builds a
live, read-only context registry from the system memory/state and binds it to
each skill before invocation, so skills can self-adapt without importing core.
"""

from typing import Any, Dict, List, Optional

from smolagents import Tool

from skills import load_skills
from skills.base_skill import BaseSkill


class MCPContext:
    """Read-only registry exposing system context to skills.

    Provides safe, delegated access to PersistentMemory and the active
    execution session status. All reads are best-effort: a missing or
    corrupted backing store yields empty/safe defaults rather than raising.
    """

    def __init__(
        self,
        memory: Any = None,
        execution_status: str = "idle",
    ) -> None:
        self._memory = memory
        self.execution_status = execution_status

    @property
    def short_term_context(self) -> str:
        try:
            return self._memory.short_term_context if self._memory else ""
        except Exception:
            return ""

    @property
    def lessons_learned(self) -> List[str]:
        try:
            return list(self._memory.lessons_learned) if self._memory else []
        except Exception:
            return []

    @property
    def failure_logs(self) -> List[Dict[str, str]]:
        try:
            return [dict(e) for e in self._memory.failure_logs] if self._memory else []
        except Exception:
            return []

    def snapshot(self) -> Dict[str, Any]:
        """Best-effort flat snapshot for debugging/logging."""
        return {
            "execution_status": self.execution_status,
            "short_term_context": self.short_term_context,
            "lessons_learned": self.lessons_learned,
            "failure_logs": self.failure_logs,
        }


def build_mcp_context(memory: Any = None, execution_status: str = "idle") -> MCPContext:
    """Construct a live MCP context registry from current system state."""
    return MCPContext(memory=memory, execution_status=execution_status)


class SkillTool(Tool):
    """Adapter wrapping a BaseSkill as a smolagents-compatible Tool.

    The engine invokes tools via ``forward(**kwargs)``; we bind the live
    MCP context and delegate to the skill's guarded ``run()`` so failures
    stay contained at the skill boundary.
    """

    def __init__(self, skill: BaseSkill, mcp_context: Optional[MCPContext] = None) -> None:
        self.name = skill.name
        self.description = skill.description
        self.inputs = getattr(skill, "inputs", {})
        self.output_type = "string"
        self._skill = skill
        # Bind context once at construction if provided (dynamic injection).
        if mcp_context is not None:
            self._skill.bind_context(mcp_context)

    def forward(self, *args, mcp_context: Optional[MCPContext] = None, **kwargs) -> object:
        # Allow per-call context override; otherwise use the bound one.
        if mcp_context is not None:
            self._skill.bind_context(mcp_context)
        elif self._skill.mcp_context is None:
            # Context-blind fallback: still run, just without awareness.
            pass
        return self._skill.run(*args, **kwargs)


def build_skill_tools(memory: Any = None) -> List[Tool]:
    """Discover all skills and wrap them as engine Tools.

    Args:
        memory: Optional PersistentMemory instance injected as MCP context.

    Returns:
        list[Tool]: Register-ready Tool objects derived from discovered skills,
        each pre-bound with a live read-only MCP context registry.
    """
    mcp_context = build_mcp_context(memory=memory) if memory is not None else None
    return [SkillTool(skill, mcp_context) for skill in load_skills()]
