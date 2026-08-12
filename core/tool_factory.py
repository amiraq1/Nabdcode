"""Dynamic Adapter: bridges pure BaseSkill objects to the engine's Tool API.

This is the ONLY module allowed to know about both ``skills`` and ``smolagents``.
Keeping the adapter here preserves total decoupling: skills/ stays engine-agnostic,
and swapping the engine means editing only this file.

It also owns the MCP (Model Context Protocol) injection: the adapter builds a
live, read-only context registry from the system memory/state and binds it to
each skill before invocation, so skills can self-adapt without importing core.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import inspect

from smolagents import Tool


@dataclass
class ToolDependencyContext:
    """PR10-05: explicit dependency bag for auto-discovery injection.

    Replaces the ad-hoc ``SimpleNamespace`` so the injection contract is
    pinned: every field ``_build_tool_with_deps`` may read is declared here,
    and callers (``AppContext.build``, tests) construct one instead of a bare
    namespace. Fields mirror the AppContext surface that tool constructors
    consume (workspace, workspace_root, workspace_dir, managers, security
    engine).
    """

    config: Any = None
    workspace: Any = None
    workspace_root: Any = None
    workspace_dir: Any = None
    memory_manager: Any = None
    todo_manager: Any = None
    _security_engine: Any = None
    memory: Any = None

    # Extra fields a future tool might need; never silently required.
    extra: Dict[str, Any] = field(default_factory=dict)

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


# Known hand-wired tool classes in core/app_context.py. Auto-discovery skips
# these so it only picks up NEW tools dropped into tools/ without re-instantiating
# the ones that need bespoke constructor args.
_MANUAL_TOOL_CLASSES = {
    "ShellTool", "FileSystemTool", "WebSearchTool", "SearchMemoryTool",
    "TodoWriteTool", "TermuxMonitorTool", "RagSearchTool",
    "CodeIntelligenceTool", "PythonREPLTool", "TasteManagerTool", "GraphifyTool",
}


def discover_tools(app_context: "Any") -> dict[str, Any]:
    """Auto-discover executable tools in ``tools/`` and inject deps from AppContext.

    Safe enhancement (PRIORITY 5, Low severity). Scans ``tools`` for ``BaseTool``
    subclasses NOT already hand-wired, matches constructor kwargs by name/type
    from the AppContext fields, and returns a name→instance dict. On ANY failure
    (missing dep, build error) the tool is skipped with a warning — never raises.
    The caller registers the result and keeps the manual block as fallback.
    """
    import importlib
    import pkgutil

    import tools as _tools_pkg
    from tools.base import BaseTool
    from tools.secure_tools import SecureTool

    # CFD-registry-1: base/intermediate classes that must never register as
    # callable tools are excluded BY CLASS IDENTITY (not by name), so a real
    # tool subclass that merely forgot to set ``name`` is surfaced loudly
    # instead of being silently dropped.
    _BASE_CLASSES = {BaseTool, SecureTool}

    discovered: dict[str, Any] = {}
    for _, module_name, _ in pkgutil.iter_modules(_tools_pkg.__path__):
        if module_name in ("base", "models", "protocols"):
            continue
        full = f"tools.{module_name}"
        try:
            module = importlib.import_module(full)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[Auto-Discovery] skip {module_name}: {exc}")
            continue
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if not (issubclass(obj, BaseTool) and obj is not BaseTool):
                continue
            if obj.__name__ in _MANUAL_TOOL_CLASSES:
                continue
            if obj in _BASE_CLASSES:
                continue
            # CFD-registry-1: a non-base class carrying the placeholder name is
            # a real tool that forgot to override ``name`` — visible skip, not
            # silent. ``register()`` would also reject it (ValueError).
            tool_name = getattr(obj, "name", None)
            if tool_name in (None, "", "unnamed_tool"):
                print(f"[Auto-Discovery] skip {obj.__name__}: missing 'name' "
                      f"(found placeholder {tool_name!r})")
                continue
            tool = _build_tool_with_deps(obj, app_context)
            if tool is not None:
                discovered[getattr(tool, "name", _name)] = tool
    return discovered


def _build_tool_with_deps(tool_cls: "Any", app_context: "Any") -> "Any | None":
    """Instantiate ``tool_cls`` by matching its __init__ kwargs to AppContext.

    Returns None (skip) when a required, non-defaulted kwarg cannot be resolved.
    """
    try:
        sig = inspect.signature(tool_cls.__init__)
    except (ValueError, TypeError):
        return None
    ctx_fields = {
        "workspace": getattr(app_context, "config", None) and getattr(app_context.config, "workspace_root", "."),
        "workspace_root": getattr(app_context, "config", None) and getattr(app_context.config, "workspace_root", "."),
        # CFD-appctx-1: BrowserTool requires workspace_dir (required kwarg).
        "workspace_dir": getattr(app_context, "config", None) and getattr(app_context.config, "workspace_root", "."),
        "memory_manager": getattr(app_context, "memory_manager", None),
        "todo_manager": getattr(app_context, "todo_manager", None),
        "security_engine": getattr(app_context, "_security_engine", None),
        "memory": getattr(app_context, "memory_manager", None),
    }
    kwargs: dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if pname in ("self", "args", "kwargs"):
            continue
        if pname in ctx_fields and ctx_fields[pname] is not None:
            kwargs[pname] = ctx_fields[pname]
        elif param.default is inspect.Parameter.empty:
            # CFD-appctx-1: a required kwarg with no injectable source is a
            # VISIBLE skip (reasoned + actionable), never a silent drop.
            print(f"[Auto-Discovery] skip {tool_cls.__name__}: required kwarg "
                  f"'{pname}' has no injectable source")
            return None
    try:
        return tool_cls(**kwargs)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[Auto-Discovery] build failed for {tool_cls.__name__}: {exc}")
        return None
