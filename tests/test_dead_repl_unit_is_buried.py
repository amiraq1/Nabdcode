"""tests/test_dead_repl_unit_is_buried.py — V-BURY-1 red guard.

Ruling V-BURY-1 (Am, 2026-08-09): the async REPL ``run_repl`` in
ui/repl_termux.py and its exclusive helpers form a self-contained dead
cluster. Measured via AST (V-BURY-1 §1 recon, not grep):

  - run_repl (L1015-1340): zero live callers. main.py boots its own sync
    ``_run_repl`` (main.py:839) — a DIFFERENT symbol (leading underscore).
    The async run_repl was orphaned.
  - _handle_permission_command / _handle_goal_command / _handle_compact_command
    / _handle_skill_command / _process_pending_edits: referenced ONLY from
    inside run_repl (L1157/1166/1187/1177/1312) — intra-cluster references,
    not live callers.
  - class REPL: already absent from ui/repl_termux.py (V7 ruling; see
    tests/test_dead_classes_are_removed.py). Nothing to bury.
  - TerminalVisualizer (the LIVE UI, main.py:742/777) references NONE of the
    target names inside its body.

Human ruling (Am, 2026-08-09, on the red-guard FAIL of run_repl): the two
references to run_repl OUTSIDE the target definitions — the dead module
alias ``main = run_repl`` (L1343, zero callers anywhere) and the
``if __name__ == "__main__":`` self-execution gate (L1675-1684, which
rejects direct execution itself and has no external users of --raw-repl) —
are part of the same dead scaffolding and are BURIED WITH the cluster.
The burial ranges below therefore include them.

The gap: the dead cluster was still physically present, so this guard pins
the death contract BEFORE any deletion. Each contract proves absence of a
LIVE caller by ast.walk over every non-test .py file — no grep, no
subprocess, no regex (per V-BURY-1 §2). A reference that falls inside the
burial cluster (the target definitions, the dead ``main`` alias, and the
__main__ self-execution gate) is NOT a live caller: the whole cluster is
buried as one block.

Contracts (one per target — not one aggregate):
  run_repl_has_no_live_caller
  class_REPL_has_no_live_caller
  _handle_permission_command_dead
  _handle_goal_command_dead
  _handle_compact_command_dead
  _handle_skill_command_dead
  _process_pending_edits_dead
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
REPL_FILE = REPO / "ui" / "repl_termux.py"

TARGETS = (
    "run_repl",
    "REPL",
    "_handle_permission_command",
    "_handle_goal_command",
    "_handle_compact_command",
    "_handle_skill_command",
    "_process_pending_edits",
)


def _burial_ranges() -> list[tuple[int, int]]:
    """Line ranges (inclusive, 1-indexed) of the burial cluster inside
    ui/repl_termux.py: the target definitions themselves, PLUS the dead
    module alias ``main = run_repl`` and the __main__ self-execution gate
    (both buried with the cluster per the human ruling). A reference inside
    these ranges is intra-cluster and therefore not a live caller."""
    tree = ast.parse(REPL_FILE.read_text(encoding="utf-8"))
    ranges: list[tuple[int, int]] = []
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name in TARGETS
        ):
            start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            ranges.append((start, node.end_lineno))
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "main" for t in node.targets
        ):
            # Dead alias: main = run_repl (zero callers — measured).
            ranges.append((node.lineno, node.end_lineno))
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            # if __name__ == "__main__": self-execution gate of the dead REPL.
            left = node.test.left
            if (
                isinstance(left, ast.Name)
                and left.id == "__name__"
                and any(
                    isinstance(c, ast.Constant) and c.value == "__main__"
                    for c in node.test.comparators
                )
            ):
                ranges.append((node.lineno, node.end_lineno))
    return ranges


def _production_files() -> list[pathlib.Path]:
    """Every .py file under the repo, excluding tests/, __pycache__ and .kimchi/."""
    out: list[pathlib.Path] = []
    for path in REPO.rglob("*.py"):
        parts = path.parts
        if "tests" in parts or "__pycache__" in parts or ".kimchi" in parts:
            continue
        out.append(path)
    return out


def _live_references(name: str) -> list[tuple[str, int]]:
    """(file, lineno) of every reference to `name` that is NOT inside the
    burial cluster. Empty ⇒ the name has no live caller."""
    burial = _burial_ranges()
    hits: list[tuple[str, int]] = []
    for path in _production_files():
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            ref = None
            if isinstance(node, ast.Name) and node.id == name:
                ref = node
            elif isinstance(node, ast.Attribute) and node.attr == name:
                ref = node
            if ref is None or not hasattr(ref, "lineno"):
                continue
            # Definition sites inside repl_termux are not references.
            if (
                path == REPL_FILE
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == name
            ):
                continue
            # Intra-cluster references are not live callers.
            if path == REPL_FILE and any(
                s <= ref.lineno <= e for s, e in burial
            ):
                continue
            hits.append((str(path.relative_to(REPO)), ref.lineno))
    return hits


def test_run_repl_has_no_live_caller():
    """run_repl must have zero live callers in production code."""
    assert _live_references("run_repl") == [], (
        "run_repl has live callers: "
        + ", ".join(f"{f}:{l}" for f, l in _live_references("run_repl"))
    )


def test_class_REPL_has_no_live_caller():
    """class REPL must be absent (V7) and have zero live callers."""
    tree = ast.parse(REPL_FILE.read_text(encoding="utf-8"))
    repl_classes = [
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "REPL"
    ]
    assert not repl_classes, (
        "class REPL exists again in ui/repl_termux.py — V7 ruling buried it."
    )
    assert _live_references("REPL") == [], (
        "REPL has live callers: "
        + ", ".join(f"{f}:{l}" for f, l in _live_references("REPL"))
    )


def test_handle_permission_command_dead():
    assert _live_references("_handle_permission_command") == [], (
        "_handle_permission_command has live callers: "
        + ", ".join(f"{f}:{l}" for f, l in _live_references("_handle_permission_command"))
    )


def test_handle_goal_command_dead():
    assert _live_references("_handle_goal_command") == [], (
        "_handle_goal_command has live callers: "
        + ", ".join(f"{f}:{l}" for f, l in _live_references("_handle_goal_command"))
    )


def test_handle_compact_command_dead():
    assert _live_references("_handle_compact_command") == [], (
        "_handle_compact_command has live callers: "
        + ", ".join(f"{f}:{l}" for f, l in _live_references("_handle_compact_command"))
    )


def test_handle_skill_command_dead():
    assert _live_references("_handle_skill_command") == [], (
        "_handle_skill_command has live callers: "
        + ", ".join(f"{f}:{l}" for f, l in _live_references("_handle_skill_command"))
    )


def test_process_pending_edits_dead():
    assert _live_references("_process_pending_edits") == [], (
        "_process_pending_edits has live callers: "
        + ", ".join(f"{f}:{l}" for f, l in _live_references("_process_pending_edits"))
    )
