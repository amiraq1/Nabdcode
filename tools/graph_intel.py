from __future__ import annotations

import json
import shutil
import time
from enum import Enum
from pathlib import Path
from typing import Final

from tools.base import BaseTool
from tools.models import ToolResult
from core.sanitize import sanitize
from core.kernel.subprocess_guard import default_guard


class GraphAction(str, Enum):
    STATUS = "status"
    BUILD = "build"
    QUERY = "query"
    PATH = "path"
    EXPLAIN = "explain"


MAX_OUTPUT_CHARS = 12000
BUILD_TIMEOUT = 900   # tree-sitter local parse of a whole repo (offline, no LLM)
QUERY_TIMEOUT = 120
GRAPH_DIR = "graphify-out"
GRAPH_JSON = "graph.json"
GRAPH_REPORT = "GRAPH_REPORT.md"


class GraphIntelTool(BaseTool):
    """Query a prebuilt project knowledge graph instead of re-listing/reading files."""

    name: Final[str] = "graph_intel"
    description: Final[str] = (
        "Query a prebuilt knowledge graph of the WHOLE project instead of listing/reading "
        "files one by one. PREFER THIS over file_system for understanding structure, "
        "dependencies, and cross-file relationships. Required arg: 'action'. Actions: "
        "'status' (is a graph built and how fresh?); "
        "'build' (build/refresh the graph ONCE — run first if status says missing); "
        "'query' (arg 'question': plain-language question -> scoped subgraph); "
        "'path' (args 'source','target': shortest relationship path between two symbols); "
        "'explain' (arg 'name': one concept and all its connections). "
        "Every edge is tagged EXTRACTED (explicit in source) or INFERRED (derived)."
    )

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()

    # ---------------------------------------------------------------------
    # helpers
    # ---------------------------------------------------------------------

    @property
    def _graph_json(self) -> Path:
        return self.workspace / GRAPH_DIR / GRAPH_JSON

    def _cli(self) -> str | None:
        return shutil.which("graphify")

    def _run_cli(self, args: list[str], timeout: int) -> ToolResult:
        exe = self._cli()
        if not exe:
            return ToolResult(
                success=False,
                stderr=(
                    "graphify CLI not found on PATH. Install ONCE with "
                    "'uv tool install graphifyy' (double-y), then 'uv tool update-shell' "
                    "and open a new terminal."
                ),
            )
        try:
            proc = default_guard.run_infra(
                [exe, *args],
                cwd=str(self.workspace),
                timeout=timeout,
            )
        except FileNotFoundError:
            return ToolResult(success=False, stderr=f"{exe} not found on PATH.")
        except Exception as exc:
            return ToolResult(success=False, stderr=f"{type(exc).__name__}: {exc}")

        out = (proc[1] or "").strip()
        err = (proc[2] or "").strip()
        ok = proc[0] == 0
        text = out if ok else (err or out or "graphify failed with no output.")
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + "\n\n... [TRUNCATED graph output]"
        text = sanitize(text, preserve_newlines=True)
        return ToolResult(
            success=ok,
            stdout=text if ok else "",
            stderr="" if ok else text,
            returncode=proc.returncode,
        )

    # ---------------------------------------------------------------------
    # dispatch
    # ---------------------------------------------------------------------

    def execute(self, **kwargs) -> ToolResult:
        raw = kwargs.get("action")
        if not isinstance(raw, str):
            return ToolResult(
                success=False,
                stderr="Missing required argument 'action'. Allowed: status, build, query, path, explain.",
            )
        try:
            action = GraphAction(raw.lower().strip())
        except ValueError:
            return ToolResult(
                success=False,
                stderr="Unsupported action. Allowed: status, build, query, path, explain.",
            )

        if action is GraphAction.STATUS:
            return self._status()
        if action is GraphAction.BUILD:
            return self._build()

        # query/path/explain need a prebuilt graph
        if not self._graph_json.exists():
            return ToolResult(
                success=False,
                stderr=(
                    "No knowledge graph found (graphify-out/graph.json missing). "
                    "Call graph_intel with action='build' ONCE first, then query."
                ),
            )

        if action is GraphAction.QUERY:
            q = kwargs.get("question") or kwargs.get("query")
            if not isinstance(q, str) or not q.strip():
                return ToolResult(success=False, stderr="action='query' requires 'question' (str).")
            return self._run_cli(["query", q.strip()], QUERY_TIMEOUT)

        if action is GraphAction.PATH:
            src = kwargs.get("source")
            dst = kwargs.get("target")
            if not (isinstance(src, str) and src.strip() and isinstance(dst, str) and dst.strip()):
                return ToolResult(success=False, stderr="action='path' requires 'source' and 'target' (str).")
            return self._run_cli(["path", src.strip(), dst.strip()], QUERY_TIMEOUT)

        if action is GraphAction.EXPLAIN:
            name = kwargs.get("name") or kwargs.get("concept")
            if not isinstance(name, str) or not name.strip():
                return ToolResult(success=False, stderr="action='explain' requires 'name' (str).")
            return self._run_cli(["explain", name.strip()], QUERY_TIMEOUT)

        return ToolResult(success=False, stderr="Unsupported operation.")

    # ---------------------------------------------------------------------
    # actions
    # ---------------------------------------------------------------------

    def _status(self) -> ToolResult:
        gj = self._graph_json
        if not gj.exists():
            return ToolResult(success=True, stdout="No graph built yet. Run action='build' once.")
        try:
            st = gj.stat()
            age_min = int((time.time() - st.st_mtime) / 60)
            nodes = edges = None
            try:
                data = json.loads(gj.read_text(encoding="utf-8", errors="replace"))
                nodes = len(data.get("nodes", []))
                edges = len(data.get("edges", []))
            except Exception:
                pass
            report = self.workspace / GRAPH_DIR / GRAPH_REPORT
            msg = [f"Graph present: {GRAPH_DIR}/{GRAPH_JSON} ({st.st_size} bytes, built ~{age_min} min ago)."]
            if nodes is not None:
                msg.append(f"Nodes: {nodes}, Edges: {edges}.")
            if report.exists():
                msg.append(f"Report available: {GRAPH_DIR}/{GRAPH_REPORT}.")
            msg.append("Use action='query'/'path'/'explain' instead of reading files.")
            return ToolResult(success=True, stdout="\n".join(msg))
        except Exception as exc:
            return ToolResult(success=False, stderr=f"{type(exc).__name__}: {exc}")

    def _build(self) -> ToolResult:
        # Fixed, injection-free command: '.' = whole workspace.
        # Code is parsed locally with tree-sitter (no LLM, nothing leaves the machine).
        return self._run_cli(["."], BUILD_TIMEOUT)
