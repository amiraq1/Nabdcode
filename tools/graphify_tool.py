# tools/graphify_tool.py
"""tools/graphify_tool.py — Graphify Knowledge Graph Tool.

Consults the graphify knowledge graph (in graphify-out/) for codebase and architecture questions.
Translates agent requests into local 'graphify' CLI invocations with timeout protection and fail-safe handling.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final, Optional

from core.kernel.subprocess_guard import default_guard

try:
    from pydantic import BaseModel, Field
except Exception:
    from tools.base import BaseModel, Field

from tools.base import BaseTool
from tools.models import ToolResult


class GraphifyArgs(BaseModel):
    """Pydantic schema for GraphifyTool arguments."""
    action: str = Field(
        ...,
        description="The graphify action to perform: 'query', 'path', 'explain', or 'update'.",
    )
    target: Optional[str] = Field(
        None,
        description="The search query, concept to explain, or the source node for 'path' action.",
    )
    target_b: Optional[str] = Field(
        None,
        description="The destination node. ONLY used when action is 'path'.",
    )


class GraphifyTool(BaseTool):
    """Consult the graphify knowledge graph for codebase structure and architecture details."""

    name: Final[str] = "graphify_tool"
    description: Final[str] = (
        "Consult the graphify knowledge graph for codebase and architecture questions. "
        "Use 'query <question>' for general structure, 'path <A> <B>' for relationships between components, "
        "'explain <concept>' for focused details, and 'update' after modifying code files."
    )
    args_schema = GraphifyArgs

    def __init__(self, workspace_dir: str | Path = ".", workspace: str | Path | None = None, **kwargs: Any) -> None:
        super().__init__()
        path_arg = workspace or workspace_dir or kwargs.get("workspace") or kwargs.get("workspace_dir") or "."
        self.workspace_dir = str(Path(path_arg).resolve())

    def forward(self, action: str, target: Optional[str] = None, target_b: Optional[str] = None, **kwargs: Any) -> str:
        """Smolagents and direct execution entry point."""
        graph_dir = os.path.join(self.workspace_dir, "graphify-out")
        if action != "update" and not os.path.exists(graph_dir):
            return "Error: graphify-out/ directory not found. Please run 'graphify update .' first (or invoke with action='update') to generate the graph."

        cmd = ["graphify", action]

        if action in ["query", "explain"]:
            if not target:
                return f"Error: Action '{action}' requires a 'target' argument."
            cmd.append(target)

        elif action == "path":
            if not target or not target_b:
                return "Error: Action 'path' requires both 'target' (Node A) and 'target_b' (Node B)."
            cmd.extend([target, target_b])

        elif action == "update":
            cmd.append(".")

        else:
            return "Error: Invalid action. Supported actions are 'query', 'path', 'explain', 'update'."

        try:
            result = default_guard.run_infra(
                cmd,
                cwd=self.workspace_dir,
                timeout=30,
            )

            output = result[1].strip()
            error = result[2].strip()

            if result[0] != 0:
                return f"Graphify CLI Error [{result[0]}]: {error or output}"

            return output if output else f"Success: Action '{action}' completed with no output."

        except FileNotFoundError:
            return "Execution Error: 'graphify' command not found. Is it installed and in your system PATH?"
        except Exception as e:
            return f"Unexpected Error: {str(e)}"

    def execute(self, action: str, target: Optional[str] = None, target_b: Optional[str] = None) -> ToolResult:
        """Native engine execution entry point."""
        out = self.forward(action=action, target=target, target_b=target_b)
        success = not out.startswith("Error:") and not out.startswith("Execution Error:") and not out.startswith("Graphify CLI Error")
        return ToolResult(
            success=success,
            stdout=out if success else "",
            stderr=out if not success else "",
            returncode=0 if success else 1,
            status="done" if success else "error",
        )
