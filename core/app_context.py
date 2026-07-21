"""AppContext — single source of truth for application singletons.

Replaces the fragile 7-element tuple returned by setup_system().
Adding a new service is a one-field addition instead of a multi-line
destructuring change at every call site.
"""

from __future__ import annotations

import atexit
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.config import AgentConfig
from core.evidence import EvidenceLog
from core.logger import Logger
from core.metrics import MetricsEngine
from core.storage import MemoryManager, SessionManager, UnifiedStorage
from core.adapters import _KernelSecurityEngine
from core.parser import pin_workspace_root
from core.todo import TodoManager
from core.snapshot import SnapshotEngine
from engine.renderer import Renderer
from engine.tool_registry import registry
from tools import ShellTool, FileSystemTool, WebSearchTool, SearchMemoryTool, RagSearchTool, CodeIntelligenceTool, PythonREPLTool, TasteManagerTool, GraphifyTool, GraphIntelTool
from tools.todo import TodoWriteTool
from tools.termux_monitor import TermuxMonitorTool


@dataclass
class AppContext:
    """Holds every long-lived singleton the application needs."""

    config: AgentConfig
    logger: Logger
    metrics: MetricsEngine
    renderer: Renderer
    session_manager: SessionManager
    memory_manager: MemoryManager
    todo_manager: TodoManager
    evidence_log: EvidenceLog
    snapshot_engine: SnapshotEngine
    storage: Optional[UnifiedStorage] = None

    @classmethod
    def build(cls, auto_discover: bool = True) -> AppContext:
        """Create and wire every singleton. Register cleanup handlers.

        Args:
            auto_discover: When True (default), auto-discover new BaseTool
                subclasses in tools/ after the manual registration block.
                Pass False to disable discovery (manual block only).
        """
        config = AgentConfig()
        pin_workspace_root(config.workspace_root)
        storage = UnifiedStorage(root_dir=Path(config.root_dir))
        storage.set_sqlite_path(os.path.join(config.root_dir, "workspace_memory.db"))
        session_mgr = storage.session_manager
        memory_mgr = storage.memory_manager
        todo_manager = storage.todo_manager
        evidence_log = storage._get_evidence_log(max_records=config.max_evidence_records)
        logger = Logger(log_dir=config.log_dir)
        metrics = MetricsEngine()
        renderer = Renderer()

        # ── Snapshot engine (pre-write backups, enables /undo) ───────────
        snapshot_engine = SnapshotEngine(workspace_root=config.workspace_root)

        # Register all tools
        _security_engine = _KernelSecurityEngine()
        # Phase 1.1: GraphifyTool needs the graphify CLI + a built graph
        # (graphify-out/graph.json). When absent, registering it lets the model
        # waste exploration steps on "command not found", starving the >=3-read
        # convergence gate. Register it only when the graph actually exists —
        # self-heals once graphify is fixed and the graph is built.
        from pathlib import Path as _Path
        _tool_classes = [ShellTool, FileSystemTool, WebSearchTool,
                         SearchMemoryTool, TodoWriteTool, TermuxMonitorTool,
                         RagSearchTool, CodeIntelligenceTool, PythonREPLTool, TasteManagerTool]
        if _Path(config.root_dir, "graphify-out", "graph.json").exists():
            _tool_classes.append(GraphifyTool)
        for tool_cls in _tool_classes:
            tool = (
                tool_cls(workspace=config.root_dir, snapshot_engine=snapshot_engine)
                if tool_cls is FileSystemTool
                else tool_cls(workspace=config.root_dir)
                if tool_cls in (CodeIntelligenceTool, PythonREPLTool, TasteManagerTool, GraphifyTool)
                else SearchMemoryTool(memory_manager=memory_mgr)
                if tool_cls is SearchMemoryTool
                else TodoWriteTool(todo_manager=todo_manager)
                if tool_cls is TodoWriteTool
                else ShellTool(security_engine=_security_engine)
                if tool_cls is ShellTool
                else RagSearchTool(workspace_root=config.root_dir)
                if tool_cls is RagSearchTool
                else tool_cls()
            )
            try:
                registry.register(tool)
            except ValueError:
                pass

        # PRIORITY 5 (optional, safe): auto-discover any NEW BaseTool subclasses
        # in tools/ not covered by the manual block above. Manual registration
        # remains the authoritative fallback; discovery only ADDS, never removes.
        try:
            from core.tool_factory import discover_tools

            for _name, _tool in discover_tools(cls).items():
                if _name not in registry:
                    try:
                        registry.register(_tool)
                    except ValueError:
                        pass
        except Exception as _disc_exc:  # fail-open: never break boot on discovery
            print(f"⚠️ [Auto-Discovery] skipped: {_disc_exc}")

        ctx = cls(
            config=config,
            logger=logger,
            metrics=metrics,
            renderer=renderer,
            session_manager=session_mgr,
            memory_manager=memory_mgr,
            todo_manager=todo_manager,
            evidence_log=evidence_log,
            snapshot_engine=snapshot_engine,
            storage=storage,
        )

        atexit.register(renderer.shutdown)
        atexit.register(logger.shutdown)
        atexit.register(storage.close)

        # ── Subagent delegation tool (task) ──────────────────────────────
        # Registers as "task". It lazily resolves the live router at call time
        # (avoids an import-order cycle with llm_router at build()). The bare
        # name "task" is what the dispatcher short-circuits on. Fail-open so a
        # broken import never breaks agent boot.
        try:
            from tools.task_tool import TaskTool

            if "task" not in registry:
                registry.register("task", TaskTool(app_context=ctx))
        except Exception as _task_exc:  # fail-open
            print(f"⚠️ [task tool] registration skipped: {_task_exc}")

        return ctx

