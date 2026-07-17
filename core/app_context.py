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
from engine.renderer import Renderer
from engine.tool_registry import registry
from tools import ShellTool, FileSystemTool, WebSearchTool, SearchMemoryTool
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
    storage: Optional[UnifiedStorage] = None

    @classmethod
    def build(cls) -> AppContext:
        """Create and wire every singleton. Register cleanup handlers."""
        config = AgentConfig()
        pin_workspace_root(config.workspace_root)
        storage = UnifiedStorage(root_dir=Path(config.root_dir))
        storage.set_sqlite_path(os.path.join(config.root_dir, "workspace_memory.db"))
        session_mgr = storage._get_session_mgr()
        memory_mgr = storage._get_memory_mgr()
        todo_manager = storage._get_todo_mgr()
        evidence_log = storage._get_evidence_log(max_records=config.max_evidence_records)
        logger = Logger(log_dir=config.log_dir)
        metrics = MetricsEngine()
        renderer = Renderer()

        # Register all tools
        _security_engine = _KernelSecurityEngine()
        for tool_cls in [ShellTool, FileSystemTool, WebSearchTool,
                         SearchMemoryTool, TodoWriteTool, TermuxMonitorTool]:
            tool = (
                tool_cls(workspace=config.root_dir)
                if tool_cls is FileSystemTool
                else SearchMemoryTool(memory_manager=memory_mgr)
                if tool_cls is SearchMemoryTool
                else TodoWriteTool(todo_manager=todo_manager)
                if tool_cls is TodoWriteTool
                else ShellTool(security_engine=_security_engine)
                if tool_cls is ShellTool
                else tool_cls()
            )
            try:
                registry.register(tool)
            except ValueError:
                pass

        ctx = cls(
            config=config,
            logger=logger,
            metrics=metrics,
            renderer=renderer,
            session_manager=session_mgr,
            memory_manager=memory_mgr,
            todo_manager=todo_manager,
            evidence_log=evidence_log,
            storage=storage,
        )

        atexit.register(renderer.shutdown)
        atexit.register(logger.shutdown)
        atexit.register(storage.close)

        return ctx

