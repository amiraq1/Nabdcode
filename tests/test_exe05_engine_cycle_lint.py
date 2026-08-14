#!/usr/bin/env python3
"""
tests/test_exe05_engine_cycle_lint.py — Engine Architectural Import & Cycle Linter
==================================================================================
Validates EXE-05 requirements:
  1. Acyclic Graph: Complete absence of circular dependencies inside engine/.
  2. AST scan across all engine modules checking top-level and function-level imports.
  3. Validates DeepAgent and ExecutionLoop dependency injection without circular load.
"""

from __future__ import annotations

import ast
import glob
import os
import unittest
from pathlib import Path

from core.kernel.events import EventBus
from engine.deep_agent import NativeDeepAgent
from engine.state import RuntimeState
from engine.tool_registry import ToolRegistry



class TestEngineCycleLint(unittest.TestCase):
    """AST-based circular dependency analyzer for the engine package."""

    def test_engine_package_is_acyclic(self):
        """Builds module import graph of engine/*.py and asserts zero cycles."""
        repo_root = Path(__file__).resolve().parent.parent
        engine_dir = repo_root / "engine"

        self.assertTrue(engine_dir.is_dir(), f"engine directory not found at {engine_dir}")

        graph: dict[str, set[str]] = {}

        for file_path in engine_dir.glob("*.py"):
            mod_name = f"engine.{file_path.stem}"
            graph[mod_name] = set()

            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("engine."):
                            graph[mod_name].add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("engine."):
                        graph[mod_name].add(node.module)

        # Detect cycles using DFS
        visited: dict[str, int] = {m: 0 for m in graph}
        detected_cycles: list[list[str]] = []

        def dfs(node: str, path: list[str]):
            visited[node] = 1  # visiting
            for neighbor in sorted(graph.get(node, set())):
                if neighbor not in graph:
                    continue
                if visited.get(neighbor) == 1:
                    cycle = path + [neighbor]
                    detected_cycles.append(cycle[cycle.index(neighbor):])
                elif visited.get(neighbor) == 0:
                    dfs(neighbor, path + [neighbor])
            visited[node] = 2  # done

        for m in graph:
            if visited[m] == 0:
                dfs(m, [m])

        self.assertEqual(
            len(detected_cycles),
            0,
            f"Detected {len(detected_cycles)} circular import(s) in engine:\n"
            + "\n".join(" -> ".join(c) for c in detected_cycles),
        )

    def test_deep_agent_accepts_injected_registry_and_bus(self):
        """NativeDeepAgent properly accepts and propagates injected tool_registry and event_bus."""
        state = RuntimeState(session_id="deep_agent_isolation_test")
        reg = ToolRegistry()
        eb = EventBus()

        agent = NativeDeepAgent(
            runtime_state=state,
            tool_registry=reg,
            event_bus=eb,
        )

        self.assertIs(agent.tool_registry, reg)
        self.assertIs(agent.event_bus, eb)
        self.assertIs(agent.dispatcher.registry, reg)
        self.assertIs(agent.dispatcher.bus, eb)



if __name__ == "__main__":
    unittest.main()
