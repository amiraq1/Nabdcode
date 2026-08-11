"""tests/test_regen_manifest_script.py — MAINT-1: manifest regeneration script.

Red-guard tests verifying that ``scripts/regen_manifest.py`` extracts the
same AST sites as the live manifest and is idempotent.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.regen_manifest as regen  # noqa: E402

from tests.test_gate_l1_loop_semantics import (  # noqa: E402
    TestGateL1TruthTableSemantics as GateTest,
)


# ── ع1: extract_matches_live_manifest ────────────────────────────────────────

def test_extract_matches_live_manifest() -> None:
    live = regen.extract_sites()
    manifest = sorted(GateTest.MANIFEST_AST_SITES)
    assert live == manifest, (
        "regen_manifest.extract_sites() must match the live manifest "
        "(run `python3 scripts/regen_manifest.py` to regenerate)"
    )


# ── ع2: find_retry_anchor_synthetic ──────────────────────────────────────────

def test_find_retry_anchor_synthetic() -> None:
    source = (
        "def _note_provider_failure(self, err):\n"
        "    if self._provider_fail_streak >= MAX:\n"
        "        return _LoopSignal.TERMINATE\n"
        "    return _LoopSignal.CONTINUE\n"
    )
    anchor = regen.find_retry_anchor(source)
    assert anchor == (3, 4)


# ── ع3: rewrite_idempotent ───────────────────────────────────────────────────

def test_rewrite_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        test_path = Path(tmp) / "test_manifest.py"
        # Original content differs from the regenerated sites: the first
        # rewrite must change it (return True), the second must be a no-op.
        test_path.write_text(
            "MANIFEST_AST_SITES = [\n"
            "        ('engine/loop.py', 999, 'TERMINATE'),\n"
            "    ]\n"
        )
        sites = [("engine/loop.py", 1, "TERMINATE")]
        anchor = (2, 3)

        first = regen.rewrite_test_file(test_path, sites, anchor)
        assert first is True
        second = regen.rewrite_test_file(test_path, sites, anchor)
        assert second is False
