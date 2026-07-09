"""AppContext — single source of truth for application singletons.

Replaces the fragile 7-element tuple returned by setup_system().
Adding a new service is a one-field addition instead of a multi-line
destructuring change at every call site.
"""

from __future__ import annotations

import atexit
import os
from dataclasses import dataclass

from core.config import AgentConfig
from core.logger import Logger
from core.metrics import MetricsEngine
from core.memory import MemoryManager
from core.session import SessionManager
from core.todo import TodoManager
from engine.renderer import Renderer
from engine.tool_registry import registry
from tools import ShellTool, FileSystemTool, WebSearchTool, SearchMemoryTool
from tools.todo import TodoWriteTool


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

    @classmethod
    def build(cls) -> AppContext:
        """Create and wire every singleton. Register cleanup handlers."""
        config = AgentConfig()
        session_mgr = SessionManager(root=config.session_dir)
        logger = Logger(log_dir=config.log_dir)
        metrics = MetricsEngine()
        memory_mgr = MemoryManager(db_path=os.path.join(config.root_dir, "workspace_memory.db"))
        renderer = Renderer()
        todo_manager = TodoManager()

        # Register all tools
        for tool_cls in [ShellTool, FileSystemTool, WebSearchTool,
                         SearchMemoryTool, TodoWriteTool]:
            tool = (
                tool_cls(workspace=config.root_dir)
                if tool_cls is FileSystemTool
                else SearchMemoryTool(memory_manager=memory_mgr)
                if tool_cls is SearchMemoryTool
                else TodoWriteTool(todo_manager=todo_manager)
                if tool_cls is TodoWriteTool
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
        )

        atexit.register(renderer.shutdown)
        atexit.register(logger.shutdown)
        atexit.register(memory_mgr.close)

        return ctx
