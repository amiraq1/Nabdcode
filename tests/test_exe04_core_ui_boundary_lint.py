#!/usr/bin/env python3
"""
tests/test_exe04_core_ui_boundary_lint.py — Architecture Boundary Linter (core -> ui)
====================================================================================
Validates EXE-04 requirements:
  1. Strict Architectural Boundary: core/ must NEVER import from ui/.
  2. AST scan over 100% of python files in core/ directory.
  3. Verifies zero Import or ImportFrom references to the 'ui' module package.
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path


class TestCoreUiBoundaryLint(unittest.TestCase):
    """Deterministic AST-based architectural boundary linter."""

    def test_core_has_zero_imports_from_ui(self):
        """Scans all python files under core/ and asserts zero imports from ui/."""
        repo_root = Path(__file__).resolve().parent.parent
        core_dir = repo_root / "core"

        self.assertTrue(core_dir.is_dir(), f"core directory not found at {core_dir}")

        violations = []
        file_count = 0

        for root, _, files in os.walk(core_dir):
            for file in files:
                if not file.endswith(".py"):
                    continue

                file_path = Path(root) / file
                rel_path = file_path.relative_to(repo_root)
                file_count += 1

                try:
                    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
                except Exception as exc:
                    self.fail(f"Failed to parse {rel_path}: {exc}")

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == "ui" or alias.name.startswith("ui."):
                                violations.append(f"{rel_path}:{node.lineno}: import {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module == "ui" or (node.module and node.module.startswith("ui.")):
                            names = ", ".join(a.name for a in node.names)
                            violations.append(f"{rel_path}:{node.lineno}: from {node.module} import {names}")

        self.assertGreater(file_count, 10, "Should have scanned at least 10 core files")
        self.assertEqual(
            len(violations),
            0,
            f"Found {len(violations)} architectural boundary violation(s) (core importing ui):\n"
            + "\n".join(f"  - {v}" for v in violations),
        )

    def test_arabic_scan_intent_accessible_from_core_and_ui(self):
        """Validates that _detect_arabic_scan_intent works identically from core and ui re-export."""
        from core.commands.auto_scan import _detect_arabic_scan_intent as core_detect
        from ui.repl_termux import _detect_arabic_scan_intent as ui_detect

        test_phrases = [
            ("افحص المستودع", True),
            ("فحر الكود", True),
            ("استكشاف المشروع", True),
            ("اكتب كود جديد", False),
            ("مرحبا بك", False),
        ]

        for phrase, expected in test_phrases:
            self.assertEqual(core_detect(phrase), expected, f"Core failed on: {phrase}")
            self.assertEqual(ui_detect(phrase), expected, f"UI re-export failed on: {phrase}")

    def test_collapse_store_accessible_from_core_and_ui(self):
        """Validates that collapse_store operates as a shared singleton between core and ui."""
        from core.kernel.collapse import collapse_store as core_store
        from ui.cc_style import collapse_store as ui_store

        self.assertIs(core_store, ui_store, "ui.cc_style must re-export the exact core collapse_store instance")

        cid = core_store.store(["line1", "line2"])
        expanded = ui_store.expand(cid)
        self.assertEqual(expanded, ["line1", "line2"])


if __name__ == "__main__":
    unittest.main()
