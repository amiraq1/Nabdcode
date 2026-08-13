# tools/code_intelligence.py
"""
Code Intelligence Tool — structural AST explorer for Python, C++, and Rust.

Provides:
  • list_symbols   — structural inventory of classes, methods, and functions with line ranges and docstrings.
  • get_definition — precise definition location (file path, line range, docstring, signature preview) for any symbol across the workspace.

ARCH-2: C++ and Rust parsing uses tree-sitter when the language packages
(``tree_sitter_cpp`` / ``tree_sitter_rust``) are installed; otherwise a
regex-based fallback parser is used so the tool remains functional in
minimal environments (e.g. Termux without a C toolchain).
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple, Type

from tools.base import BaseModel, BaseTool, Field
from tools.models import ToolResult
from tools.action_contract import invalid_action_result, normalize_action


# ── ARCH-2: Language support matrix ────────────────────────────────────────
_SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py":  "python",
    ".cpp": "cpp",
    ".cc":  "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h":   "cpp",
    ".rs":  "rust",
}


def _get_tree_sitter_language(lang: str) -> Any | None:
    """Lazily import a tree-sitter language package.

    Returns the ``Language`` object or ``None`` if the package is not
    installed (ARCH-2 fallback path).
    """
    try:
        if lang == "cpp":
            import tree_sitter_cpp
            return tree_sitter_cpp.language()
        if lang == "rust":
            import tree_sitter_rust
            return tree_sitter_rust.language()
    except ImportError:
        return None
    return None


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
        raw_action = kwargs.get("action", "")
        action = normalize_action(raw_action)
        allowed_actions = ("list_symbols", "get_definition")
        if action not in allowed_actions:
            return invalid_action_result(self.name, raw_action, allowed_actions)

        path_str = str(kwargs.get("path", ".")).strip()
        symbol = str(kwargs.get("symbol", "")).strip()

        try:
            target = self._resolve(path_str)
        except PermissionError as exc:
            return ToolResult(success=False, stderr=str(exc))

        if action == "list_symbols":
            return self._list_symbols(target)
        else:
            return self._get_definition(target, symbol)

    def _list_symbols(self, target: Path) -> ToolResult:
        """List all classes, methods, and functions inside a source file.

        ARCH-2: Supports Python (.py), C++ (.cpp/.cc/.cxx/.h/.hpp), and
        Rust (.rs).  C++/Rust use tree-sitter when available, falling back
        to a regex-based parser otherwise.
        """
        if not target.exists():
            return ToolResult(success=False, stderr=f"File not found: {target.name}")
        if not target.is_file():
            return ToolResult(success=False, stderr=f"Target must be a file: {target.name}")

        lang = _SUPPORTED_EXTENSIONS.get(target.suffix)
        if lang is None:
            return ToolResult(
                success=False,
                stderr=f"Unsupported file type: {target.suffix}. "
                       f"Supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}",
            )

        try:
            content = target.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(success=False, stderr=f"Error reading {target.name}: {exc}")

        total_lines = len(content.splitlines())
        rel_path = target.relative_to(self.workspace) if self.workspace in target.parents else target.name
        lines = [f"Document Symbols for: {rel_path} (Total lines: {total_lines})", "-" * 60]

        if lang == "python":
            lines.extend(self._list_symbols_python(content, target))
        elif lang == "cpp":
            lines.extend(self._list_symbols_cpp(content))
        elif lang == "rust":
            lines.extend(self._list_symbols_rust(content))

        if len(lines) == 2:
            lines.append("(No classes or top-level functions defined in this file)")

        return ToolResult(
            success=True,
            stdout="\n".join(lines),
            metadata={"tool": self.name, "action": "list_symbols", "path": str(rel_path), "language": lang},
        )

    def _list_symbols_python(self, content: str, target: Path) -> List[str]:
        """Extract symbols from a Python file using the stdlib ``ast`` module."""
        try:
            tree = ast.parse(content, filename=str(target))
        except SyntaxError as exc:
            return [f"(SyntaxError parsing {target.name}: {exc})"]
        except Exception as exc:
            return [f"(Error parsing {target.name}: {exc})"]

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

        out: List[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                end_line = getattr(node, "end_lineno", node.lineno)
                doc = ast.get_docstring(node)
                doc_str = f" -- {doc.strip().splitlines()[0]}" if doc else ""
                out.append(f"class {node.name} (L{node.lineno}-L{end_line}){doc_str}")

                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        c_end = getattr(child, "end_lineno", child.lineno)
                        prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                        c_doc = ast.get_docstring(child)
                        c_doc_str = f" -- {c_doc.strip().splitlines()[0]}" if c_doc else ""
                        out.append(f"  {prefix} {child.name}({format_args(child)}) (L{child.lineno}-L{c_end}){c_doc_str}")

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", node.lineno)
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                doc = ast.get_docstring(node)
                doc_str = f" -- {doc.strip().splitlines()[0]}" if doc else ""
                out.append(f"{prefix} {node.name}({format_args(node)}) (L{node.lineno}-L{end_line}){doc_str}")

        return out

    def _list_symbols_cpp(self, content: str) -> List[str]:
        """Extract symbols from a C++ file.

        ARCH-2: Uses tree-sitter when ``tree_sitter_cpp`` is installed;
        otherwise falls back to a regex-based scanner that detects
        ``class``, ``struct``, and function definitions.
        """
        lang_obj = _get_tree_sitter_language("cpp")
        if lang_obj is not None:
            try:
                from tree_sitter import Parser
                parser = Parser(lang_obj)
                tree = parser.parse(bytes(content, "utf-8"))
                return self._tree_sitter_cpp_symbols(tree, content)
            except Exception:
                pass
        # Regex fallback
        return self._regex_cpp_symbols(content)

    def _list_symbols_rust(self, content: str) -> List[str]:
        """Extract symbols from a Rust file.

        ARCH-2: Uses tree-sitter when ``tree_sitter_rust`` is installed;
        otherwise falls back to a regex-based scanner that detects
        ``struct``, ``enum``, ``fn``, ``impl``, and ``trait`` definitions.
        """
        lang_obj = _get_tree_sitter_language("rust")
        if lang_obj is not None:
            try:
                from tree_sitter import Parser
                parser = Parser(lang_obj)
                tree = parser.parse(bytes(content, "utf-8"))
                return self._tree_sitter_rust_symbols(tree, content)
            except Exception:
                pass
        # Regex fallback
        return self._regex_rust_symbols(content)

    def _tree_sitter_cpp_symbols(self, tree: Any, content: str) -> List[str]:
        """Walk a tree-sitter C++ tree and emit symbol lines."""
        out: List[str] = []
        lines = content.splitlines()

        def _line_range(node: Any) -> str:
            start = node.start_point[0] + 1
            end = node.end_point[0] + 1
            return f"(L{start}-L{end})"

        def _walk(node: Any, indent: int = 0) -> None:
            kind = node.type
            name = None
            for child in node.children:
                if child.type == "name" or (child.type == "identifier"):
                    name = child.text.decode() if child.text else None
                    break
            if kind in ("class_definition", "struct_definition"):
                prefix = "class" if kind == "class_definition" else "struct"
                out.append(f"{'  ' * indent}{prefix} {name or '?'} {_line_range(node)}")
            elif kind == "function_definition":
                out.append(f"{'  ' * indent}fn {name or '?'} {_line_range(node)}")
            for child in node.children:
                _walk(child, indent + 1 if kind in ("class_definition", "struct_definition") else indent)

        _walk(tree.root_node)
        return out if out else ["(No symbols found via tree-sitter)"]

    def _tree_sitter_rust_symbols(self, tree: Any, content: str) -> List[str]:
        """Walk a tree-sitter Rust tree and emit symbol lines."""
        out: List[str] = []

        def _line_range(node: Any) -> str:
            start = node.start_point[0] + 1
            end = node.end_point[0] + 1
            return f"(L{start}-L{end})"

        def _walk(node: Any, indent: int = 0) -> None:
            kind = node.type
            name = None
            for child in node.children:
                if child.type == "identifier" or child.type == "type_identifier":
                    name = child.text.decode() if child.text else None
                    break
            if kind == "struct_definition":
                out.append(f"{'  ' * indent}struct {name or '?'} {_line_range(node)}")
            elif kind == "enum_definition":
                out.append(f"{'  ' * indent}enum {name or '?'} {_line_range(node)}")
            elif kind == "trait_definition":
                out.append(f"{'  ' * indent}trait {name or '?'} {_line_range(node)}")
            elif kind == "impl_definition":
                out.append(f"{'  ' * indent}impl {name or '?'} {_line_range(node)}")
            elif kind == "function_definition":
                out.append(f"{'  ' * indent}fn {name or '?'} {_line_range(node)}")
            for child in node.children:
                _walk(child, indent + 1)

        _walk(tree.root_node)
        return out if out else ["(No symbols found via tree-sitter)"]

    def _regex_cpp_symbols(self, content: str) -> List[str]:
        """Regex-based fallback for C++ symbol extraction."""
        out: List[str] = []
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments / preprocessor directives
            if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('#'):
                continue
            # class / struct definitions
            m = re.match(r'(class|struct)\s+(\w+)', stripped)
            if m:
                out.append(f"{m.group(1)} {m.group(2)} (L{i})")
                continue
            # function definitions OR declarations: return_type name(params) { or ;
            m = re.match(
                r'(?:virtual\s+|static\s+|inline\s+|const\s+|explicit\s+|friend\s+)*'
                r'[\w:<>&*\s]+?\s+(\w+)\s*\([^)]*\)\s*(?:const\s*)?[;{]',
                stripped,
            )
            if m:
                out.append(f"fn {m.group(1)} (L{i})")
        return out

    def _regex_rust_symbols(self, content: str) -> List[str]:
        """Regex-based fallback for Rust symbol extraction."""
        out: List[str] = []
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            for keyword in ("struct", "enum", "trait", "impl", "fn"):
                m = re.match(rf'{keyword}\s+(\w+)', stripped)
                if m:
                    out.append(f"{keyword} {m.group(1)} (L{i})")
                    break
        return out

    def _get_definition(self, target: Path, symbol: str) -> ToolResult:
        """Find definitions of a symbol across a target file or workspace directory.

        ARCH-2: Supports Python (.py), C++ (.cpp/.cc/.cxx/.h/.hpp), and
        Rust (.rs).  C++/Rust use regex-based symbol scanning (the
        tree-sitter language packages are optional and only used in
        ``_list_symbols``).
        """
        if not symbol:
            return ToolResult(success=False, stderr="Argument 'symbol' is required for action 'get_definition'.")

        code_files: List[Path] = []
        if target.is_file():
            if target.suffix in _SUPPORTED_EXTENSIONS:
                code_files.append(target)
        elif target.is_dir():
            for root, dirs, files in os.walk(target):
                # Prune common ignore directories
                dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".venv", "node_modules", ".pytest_cache", "target", "build")]
                for file in files:
                    if Path(file).suffix in _SUPPORTED_EXTENSIONS:
                        code_files.append(Path(root) / file)

        if not code_files:
            return ToolResult(
                success=False,
                stderr=f"No supported source files found in {target} "
                       f"(supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS))})",
            )

        matches: List[str] = []
        parts = symbol.split(".")
        target_class = parts[0] if len(parts) > 1 else None
        target_name = parts[-1]

        for code_file in sorted(code_files):
            lang = _SUPPORTED_EXTENSIONS.get(code_file.suffix)
            try:
                content = code_file.read_text(encoding="utf-8")
            except Exception:
                continue

            rel_path = code_file.relative_to(self.workspace) if self.workspace in code_file.parents else code_file.name
            file_lines = content.splitlines()

            if lang == "python":
                self._find_python_definition(matches, content, code_file, rel_path, file_lines, symbol, target_class, target_name)
            else:
                # C++ / Rust: regex scan for symbol name with line numbers
                self._find_regex_definition(matches, content, rel_path, file_lines, symbol, target_name, lang)

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

    def _find_python_definition(
        self, matches: List[str], content: str, py_file: Path, rel_path: Any,
        file_lines: List[str], symbol: str, target_class: Optional[str], target_name: str,
    ) -> None:
        """Search a Python file's AST for the target symbol and add matches."""
        try:
            tree = ast.parse(content, filename=str(py_file))
        except Exception:
            return

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

    def _find_regex_definition(
        self, matches: List[str], content: str, rel_path: Any,
        file_lines: List[str], symbol: str, target_name: str, lang: str,
    ) -> None:
        """Search a C++/Rust file via regex for the target symbol."""
        for i, line in enumerate(file_lines, 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("#") or stripped.startswith("/*"):
                continue
            if re.search(rf'\b{re.escape(target_name)}\b', stripped):
                start_line = i
                end_line = min(i + 12, len(file_lines))
                preview_str = "\n".join(f"     {l}" for l in file_lines[start_line - 1:end_line])
                match_text = (
                    f"• [{lang}] {target_name} in {rel_path} (L{start_line})\n"
                    f"   Code preview:\n{preview_str}"
                )
                matches.append(match_text)

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
