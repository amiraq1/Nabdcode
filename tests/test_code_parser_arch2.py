"""tests/test_code_parser_arch2.py — ARCH-2: C++/Rust parsing for code_intelligence.

Verifies that ``CodeIntelligenceTool`` can parse C++ headers and Rust
sources (via regex fallback when tree-sitter language packages are
absent, which is the Termux case), and that Python still works.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.code_intelligence import CodeIntelligenceTool


class TestCodeIntelligenceArch2(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.tool = CodeIntelligenceTool(workspace=self.workspace)

        # C++ header
        (self.workspace / "sample.hpp").write_text(
            "#pragma once\n"
            "\n"
            "class Widget {\n"
            "public:\n"
            "    Widget();\n"
            "    int compute(int x, int y);\n"
            "};\n"
            "\n"
            "struct Point {\n"
            "    int x;\n"
            "    int y;\n"
            "};\n"
            "\n"
            "int helper(int a);\n",
            encoding="utf-8",
        )

        # Rust source
        (self.workspace / "lib.rs").write_text(
            "struct Vector {\n"
            "    x: f64,\n"
            "    y: f64,\n"
            "}\n"
            "\n"
            "enum Direction {\n"
            "    North,\n"
            "    South,\n"
            "}\n"
            "\n"
            "fn magnitude(v: &Vector) -> f64 {\n"
            "    (v.x * v.x + v.y * v.y).sqrt()\n"
            "}\n"
            "\n"
            "impl Vector {\n"
            "    fn new(x: f64, y: f64) -> Self {\n"
            "        Vector { x, y }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    # ── ع1: cpp_headers_parsed_correctly ─────────────────────────────────

    def test_cpp_headers_parsed_correctly(self) -> None:
        """C++ header symbols are extracted (regex fallback)."""
        res = self.tool.execute(action="list_symbols", path="sample.hpp")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("class Widget", res.output)
        self.assertIn("struct Point", res.output)
        # Function definition lines
        self.assertIn("fn compute", res.output)

    # ── ع2: rust_macros_parsed_correctly ─────────────────────────────────

    def test_rust_symbols_parsed_correctly(self) -> None:
        """Rust structs/enums/fns/impls are extracted (regex fallback)."""
        res = self.tool.execute(action="list_symbols", path="lib.rs")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("struct Vector", res.output)
        self.assertIn("enum Direction", res.output)
        self.assertIn("fn magnitude", res.output)
        self.assertIn("impl Vector", res.output)

    # ── ع3: fallback_to_regex_if_ts_missing ───────────────────────────────

    def test_fallback_to_regex_if_ts_missing(self) -> None:
        """When tree-sitter language packages are absent, regex fallback works."""
        with patch("tools.code_intelligence._get_tree_sitter_language", return_value=None):
            res = self.tool.execute(action="list_symbols", path="sample.hpp")
            self.assertTrue(res.success, res.stderr)
            self.assertIn("class Widget", res.output)

            res2 = self.tool.execute(action="list_symbols", path="lib.rs")
            self.assertTrue(res2.success, res2.stderr)
            self.assertIn("struct Vector", res2.output)

    def test_python_still_works(self) -> None:
        """Python AST parsing is unaffected by ARCH-2 changes."""
        (self.workspace / "app.py").write_text(
            "class Animal:\n"
            "    def speak(self) -> str:\n"
            "        return '...'\n"
            "\n"
            "def main() -> None:\n"
            "    pass\n",
            encoding="utf-8",
        )
        res = self.tool.execute(action="list_symbols", path="app.py")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("class Animal", res.output)
        self.assertIn("def main", res.output)

    def test_unsupported_file_type(self) -> None:
        """Unsupported extensions are rejected with a clear message."""
        (self.workspace / "data.json").write_text('{"a": 1}', encoding="utf-8")
        res = self.tool.execute(action="list_symbols", path="data.json")
        self.assertFalse(res.success)
        self.assertIn("Unsupported file type", res.stderr)

    def test_get_definition_cpp(self) -> None:
        """get_definition finds symbols in C++ files."""
        res = self.tool.execute(action="get_definition", path=".", symbol="compute")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("compute", res.output)
        self.assertIn("sample.hpp", res.output)

    def test_get_definition_rust(self) -> None:
        """get_definition finds symbols in Rust files."""
        res = self.tool.execute(action="get_definition", path=".", symbol="magnitude")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("magnitude", res.output)
        self.assertIn("lib.rs", res.output)


if __name__ == "__main__":
    unittest.main()
