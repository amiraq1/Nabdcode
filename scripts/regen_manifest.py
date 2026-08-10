#!/usr/bin/env python3
"""scripts/regen_manifest.py — regenerate the L1 truth-table manifest.

Usage: python3 scripts/regen_manifest.py
Rewrites MANIFEST_AST_SITES and the retry-budget anchors in
tests/test_gate_l1_loop_semantics.py from the live AST.
Human review preserved: the regenerated diff is reviewed at commit time.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["engine/loop.py", "engine/_budget.py",
         "engine/_convergence.py", "engine/_tool_runner.py"]
TEST = ROOT / "tests" / "test_gate_l1_loop_semantics.py"


def extract_sites(files=None) -> list:
    files = [ROOT / f for f in FILES] if files is None else [Path(f) for f in files]
    sites = []
    for p in files:
        if not p.exists():
            continue
        rel = str(p.resolve().relative_to(ROOT))
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and node.value:
                val = node.value
                if isinstance(val, ast.Attribute) and getattr(val.value, "id", None) == "_LoopSignal":
                    sites.append((rel, node.lineno, val.attr))
                elif isinstance(val, ast.Tuple):
                    for elt in val.elts:
                        if isinstance(elt, ast.Attribute) and getattr(elt.value, "id", None) == "_LoopSignal":
                            sites.append((rel, node.lineno, elt.attr))
    return sorted(sites)


def find_retry_anchor(source: str):
    """(lineno of first TERMINATE return, next CONTINUE return) inside
    _note_provider_failure; None if absent."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_note_provider_failure":
            returns = sorted(
                (c for c in ast.walk(node)
                 if isinstance(c, ast.Return) and isinstance(c.value, ast.Attribute)
                 and getattr(c.value.value, "id", None) == "_LoopSignal"),
                key=lambda r: r.lineno)
            term = None
            for r in returns:
                if r.value.attr == "TERMINATE" and term is None:
                    term = r.lineno
                elif r.value.attr == "CONTINUE" and term is not None:
                    return term, r.lineno
    return None


def rewrite_test_file(test_path: Path, sites, anchor) -> bool:
    content = test_path.read_text()
    original = content

    manifest_str = "MANIFEST_AST_SITES = [\n" + "".join(
        f"        {repr(s)},\n" for s in sites) + "    ]"
    content = re.sub(r"MANIFEST_AST_SITES = \[.*?\n    \]",
                     manifest_str, content, flags=re.DOTALL)
    content = re.sub(r"assertEqual\(len\(self\.MANIFEST_AST_SITES\), \d+\)",
                     f"assertEqual(len(self.MANIFEST_AST_SITES), {len(sites)})", content)

    if anchor:
        term, cont = anchor
        content = re.sub(
            r"line_\w+ = lines\[\d+\]\s*# loop\.py line \d+ returns TERMINATE[^\n]*\n\s*self\.assertIn\(\"TERMINATE\", line_\w+\)",
            f"line_term = lines[{term - 1}]  # loop.py line {term} returns TERMINATE\n        self.assertIn(\"TERMINATE\", line_term)",
            content)
        content = re.sub(
            r"line_\w+ = lines\[\d+\]\s*# loop\.py line \d+ returns CONTINUE[^\n]*\n\s*self\.assertIn\(\"CONTINUE\", line_\w+\)",
            f"line_cont = lines[{cont - 1}]  # loop.py line {cont} returns CONTINUE\n        self.assertIn(\"CONTINUE\", line_cont)",
            content)

    if content != original:
        test_path.write_text(content)
        return True
    return False


def main() -> int:
    sites = extract_sites()
    anchor = find_retry_anchor((ROOT / "engine/loop.py").read_text())
    changed = rewrite_test_file(TEST, sites, anchor)
    if changed:
        print(f"REGENERATED: {len(sites)} sites, retry anchor {anchor}")
    else:
        print("IN_SYNC: manifest already matches live AST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
