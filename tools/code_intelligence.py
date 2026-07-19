# tools/code_intelligence.py
"""
Code Intelligence Tool — zero-dependency structural AST explorer for Python files.

Provides:
  • list_symbols   — structural inventory of classes, methods, and functions with line ranges and docstrings.
  • get_definition — precise definition location (file path, line range, docstring, signature preview) for any symbol across the workspace.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple, Type

from tools.base import BaseModel, BaseTool, Field
from tools.models import ToolResult


class CodeIntelligenceArgs(BaseModel):
    """Pydantic schema for CodeIntelligenceTool arguments."""
    action: str = Field(..., description="Action to perform: 'list_symbols' or 'get_definition'.")
    path: str = Field(".", description="File path (for 'list_symbols') or directory to search (for 'get_definition').")
    symbol: str = Field("", description="Target symbol name to search for (required for 'get_definition').")


class CodeIntelligenceTool(BaseTool):
    """Zero-dependency structural AST explorer for Python files.

    Gives agents immediate structural awareness without needing heavy external language servers.
    """

    name: Final[str] = "code_intelligence"
    description: Final[str] = (
        "AST-based structural code intelligence for Python files. "
        "Actions: 'list_symbols' (returns classes, methods, and functions with line ranges and docstrings for a file) "
        "or 'get_definition' (finds exact file path, line range, and docstring where a symbol is defined across the workspace). "
        "Required args: action, path (can be '.' or empty for get_definition across workspace). Optional: symbol."
    )
    inputs: dict = {
        "action": {
            "type": "string",
            "description": "Action to perform: 'list_symbols' or 'get_definition'.",
        },
        "path": {
            "type": "string",
            "description": "Target file path or directory within workspace.",
        },
        "symbol": {
            "type": "string",
            "description": "Symbol name (e.g., class name, function name, or Class.method). Required for 'get_definition'.",
        },
    }

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return CodeIntelligenceArgs

    def _resolve(self, relative_path: str) -> Path:
        """Resolve path safely inside the workspace."""
        if not relative_path or relative_path.strip() == "":
            relative_path = "."
        target = (self.workspace / relative_path).resolve()
        if self.workspace not in target.parents and target != self.workspace:
            raise PermissionError("Access outside the workspace is forbidden.")
        return target

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()
        path_str = str(kwargs.get("path", ".")).strip()
        symbol = str(kwargs.get("symbol", "")).strip()

        if action not in ("list_symbols", "get_definition"):
            return ToolResult(
                success=False,
                stderr="Invalid action. Allowed actions: 'list_symbols', 'get_definition'.",
            )

        try:
            target = self._resolve(path_str)
        except PermissionError as exc:
            return ToolResult(success=False, stderr=str(exc))

        if action == "list_symbols":
            return self._list_symbols(target)
        else:
            return self._get_definition(target, symbol)

    def _list_symbols(self, target: Path) -> ToolResult:
        """List all classes, methods, and functions inside a single Python file."""
        if not target.exists():
            return ToolResult(success=False, stderr=f"File not found: {target.name}")
        if not target.is_file() or target.suffix != ".py":
            return ToolResult(success=False, stderr=f"Target must be an existing Python (.py) file: {target.name}")

        try:
            content = target.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(target))
        except SyntaxError as exc:
            return ToolResult(success=False, stderr=f"SyntaxError parsing {target.name}: {exc}")
        except Exception as exc:
            return ToolResult(success=False, stderr=f"Error reading {target.name}: {exc}")

        total_lines = len(content.splitlines())
        rel_path = target.relative_to(self.workspace) if self.workspace in target.parents else target.name

        lines = [f"Document Symbols for: {rel_path} (Total lines: {total_lines})", "-" * 60]

        def format_args(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
            args = []
            for arg in func_node.args.args:
                arg_str = arg.arg
                if arg.annotation and hasattr(ast, "unparse"):
                    try:
                        arg_str += f": {ast.unparse(arg.annotation)}"
                    except Exception:
                        pass
                args.append(arg_str)
            return ", ".join(args)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                end_line = getattr(node, "end_lineno", node.lineno)
                doc = ast.get_docstring(node)
                doc_str = f" -- {doc.strip().splitlines()[0]}" if doc else ""
                lines.append(f"class {node.name} (L{node.lineno}-L{end_line}){doc_str}")

                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        c_end = getattr(child, "end_lineno", child.lineno)
                        prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                        c_doc = ast.get_docstring(child)
                        c_doc_str = f" -- {c_doc.strip().splitlines()[0]}" if c_doc else ""
                        lines.append(f"  {prefix} {child.name}({format_args(child)}) (L{child.lineno}-L{c_end}){c_doc_str}")

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", node.lineno)
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                doc = ast.get_docstring(node)
                doc_str = f" -- {doc.strip().splitlines()[0]}" if doc else ""
                lines.append(f"{prefix} {node.name}({format_args(node)}) (L{node.lineno}-L{end_line}){doc_str}")

        if len(lines) == 2:
            lines.append("(No classes or top-level functions defined in this file)")

        return ToolResult(
            success=True,
            stdout="\n".join(lines),
            metadata={"tool": self.name, "action": "list_symbols", "path": str(rel_path)},
        )

    def _get_definition(self, target: Path, symbol: str) -> ToolResult:
        """Find definitions of a symbol across a target file or workspace directory."""
        if not symbol:
            return ToolResult(success=False, stderr="Argument 'symbol' is required for action 'get_definition'.")

        py_files: List[Path] = []
        if target.is_file():
            if target.suffix == ".py":
                py_files.append(target)
        elif target.is_dir():
            for root, dirs, files in os.walk(target):
                # Prune common ignore directories
                dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".venv", "node_modules", ".pytest_cache")]
                for file in files:
                    if file.endswith(".py"):
                        py_files.append(Path(root) / file)

        if not py_files:
            return ToolResult(success=False, stderr=f"No Python (.py) files found in {target}")

        matches: List[str] = []
        parts = symbol.split(".")
        target_class = parts[0] if len(parts) > 1 else None
        target_name = parts[-1]

        for py_file in sorted(py_files):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))
            except Exception:
                continue

            rel_path = py_file.relative_to(self.workspace) if self.workspace in py_file.parents else py_file.name
            file_lines = content.splitlines()

            # Attach parent_class references for precise Class.method resolution
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    setattr(child, "parent", node)
                    if isinstance(node, ast.ClassDef):
                        setattr(child, "parent_class", node)
                    elif hasattr(node, "parent_class"):
                        setattr(child, "parent_class", getattr(node, "parent_class"))

            # Walk syntax tree
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if node.name == symbol or (target_class is None and node.name == target_name):
                        self._add_match(matches, node, rel_path, file_lines, "class")

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Check if method inside class or top-level
                    parent = getattr(node, "parent_class", None)
                    # If target specified class.method, match carefully
                    if target_class and parent and parent.name != target_class:
                        continue
                    if node.name == target_name or node.name == symbol:
                        kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                        self._add_match(matches, node, rel_path, file_lines, kind)

        if not matches:
            return ToolResult(
                success=True,
                stdout=f"No definition found for symbol '{symbol}' inside {target}",
                metadata={"tool": self.name, "action": "get_definition", "matches": 0},
            )

        output_str = f"Found {len(matches)} definition(s) for symbol '{symbol}':\n" + "-" * 60 + "\n" + "\n\n".join(matches)
        return ToolResult(
            success=True,
            stdout=output_str,
            metadata={"tool": self.name, "action": "get_definition", "matches": len(matches)},
        )

    def _add_match(self, matches: List[str], node: ast.AST, rel_path: Any, file_lines: List[str], kind: str) -> None:
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)
        doc = ast.get_docstring(node)
        doc_snippet = f"   Docstring: {doc.strip().splitlines()[0]}" if doc else ""

        # Preview lines (up to 12 lines)
        preview_end = min(start_line + 12, end_line)
        preview_lines = file_lines[start_line - 1 : preview_end]
        preview_str = "\n".join(f"     {l}" for l in preview_lines)
        if preview_end < end_line:
            preview_str += f"\n     ... ({end_line - preview_end} more lines)"

        match_text = (
            f"• [{kind}] {getattr(node, 'name', '')} in {rel_path} (L{start_line}-L{end_line})\n"
            f"{doc_snippet}\n"
            f"   Code preview:\n{preview_str}"
        )
        matches.append(match_text)
