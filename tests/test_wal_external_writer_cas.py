"""Gate: external-writer race in the WAL check-to-replace window (Option B CAS).

The accept_edits flow does check#1 -> snapshot -> PREPARED -> check#2 ->
_atomic_write (temp -> fsync -> os.replace) -> verify -> APPLIED.

Historically there was NO protection between check#2 and os.replace, so a
non-lock-sharing external writer could modify the target in that window and
be silently clobbered by os.replace.

This file contains three labeled tests:

  * test_external_writer_race_post_fix — EXPECTED PASS after fix. Proves the
    CAS guard deterministically aborts the write and preserves the external
    modification when the race lands at the pre-replace CAS seam.
    (Pre-fix this was the bug: the external write was clobbered and the edit
    was ACCEPTED.)
  * test_cas_clean_accept_preserves_wal_and_verify — EXPECTED PASS. Proves the
    CAS path does not disturb the normal accept/WAL/verify flow when the
    target is unchanged.
  * (Direct unit coverage of the CAS helper _atomic_write_if_unchanged.)
"""

import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from core.accept_edits_state import (
    accept_edit,
    reset_session,
    set_journal_path,
    set_workspace_identity,
    _close_journal,
    _accept_edits_pending,
    _compute_digest,
    _file_digest,
    _atomic_write,
    _atomic_write_if_unchanged,
    PendingEdit,
    TransactionOutcome,
    WriteStage,
)


class TestExternalWriterRace(unittest.TestCase):
    def setUp(self):
        _close_journal()
        reset_session()
        self.td = Path(tempfile.mkdtemp())
        self.jpath = str(self.td / "journal.jsonl")
        set_workspace_identity(str(self.td))
        set_journal_path(self.jpath)

    def tearDown(self):
        _close_journal()
        reset_session()

    def _setup_edit(self, content="old", new_content="new", filename="test.txt"):
        fpath = self.td / filename
        fpath.write_text(content)
        edit_id = str(uuid.uuid4())
        edit = PendingEdit(
            edit_id=edit_id,
            path=fpath.name,
            resolved_path=str(fpath),
            old_content=content,
            new_content=new_content,
            diff="",
            additions=1,
            removals=0,
            expected_original_digest=_compute_digest(content),
        )
        _accept_edits_pending.append(edit)
        return edit_id, fpath

    def _read_journal(self):
        if not os.path.exists(self.jpath):
            return []
        with open(self.jpath, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    # ------------------------------------------------------------------
    # Labeled: POST-FIX race test (deterministic, expected PASS after fix)
    # ------------------------------------------------------------------
    def test_external_writer_race_post_fix(self):
        """POST-FIX: an external writer landing in the check-to-replace window
        is preserved.

        The race is injected deterministically at the pre-replace CAS seam
        (the same seam the real thread test exercised): when the CAS check
        reads the target, an external writer has already replaced it, so the
        CAS guard aborts the replace. The external content SURVIVES and the
        edit returns CONFLICT (not ACCEPTED). Pre-fix this was the bug: the
        external write was clobbered and the edit was ACCEPTED."""
        edit_id, fpath = self._setup_edit(content="old", new_content="new")
        external = "EXTERNAL-SURVIVED-CONTENT"

        # Deterministically land the external write AT the CAS seam.
        real_file_digest = _file_digest
        flipped = {"done": False}

        def _external_write_at_cas(path):
            if not flipped["done"]:
                flipped["done"] = True
                Path(path).write_text(external)
            return real_file_digest(path)

        with mock.patch(
            "core.accept_edits_state._file_digest", side_effect=_external_write_at_cas
        ):
            res = accept_edit(edit_id)

        # POST-FIX: the external write is preserved (not clobbered).
        self.assertEqual(fpath.read_text(), external)
        # The edit is a CONFLICT, not ACCEPTED.
        self.assertEqual(res.outcome, TransactionOutcome.CONFLICT)


    # ------------------------------------------------------------------
    # Regression: CAS path must NOT disturb the normal accept/WAL/verify flow
    # ------------------------------------------------------------------
    def test_cas_clean_accept_preserves_wal_and_verify(self):
        """A clean accept (target unchanged) still emits the full WAL sequence
        and the correct result — the CAS guard is a no-op when the digest
        matches, so the existing PREPARED->APPLIED->COMMITTED->RESOLVED flow,
        the verify-after-write, and the ACCEPTED outcome are preserved."""
        edit_id, fpath = self._setup_edit(content="old", new_content="new")
        res = accept_edit(edit_id)
        self.assertEqual(res.outcome, TransactionOutcome.ACCEPTED)
        self.assertEqual(fpath.read_text(), "new")
        events = [r["event_type"] for r in self._read_journal()]
        self.assertEqual(
            events, ["PREPARED", "APPLIED", "COMMITTED", "RESOLVED"]
        )
        # The observed digest in APPLIED matches the written content (verify).
        applied = next(r for r in self._read_journal() if r["event_type"] == "APPLIED")
        self.assertEqual(applied["observed_result_digest"], _compute_digest("new"))
        # The pending queue is drained.
        self.assertEqual(len(_accept_edits_pending), 0)


    # ------------------------------------------------------------------
    # Direct unit coverage of the CAS helper itself
    # ------------------------------------------------------------------
    def test_atomic_write_if_unchanged_mismatch_preserves_target(self):
        target = self.td / "direct.txt"
        target.write_text("original")
        data = b"new content"
        expected = _compute_digest("original")
        # Simulate external writer landing just before the CAS check.
        real_file_digest = _file_digest
        flipped = {"done": False}

        def _flip(path):
            if not flipped["done"]:
                flipped["done"] = True
                Path(path).write_text("EXTERNAL")
            return real_file_digest(path)

        with mock.patch(
            "core.accept_edits_state._file_digest", side_effect=_flip
        ):
            res = _atomic_write_if_unchanged(target, data, expected)
        self.assertFalse(res.applied)
        self.assertEqual(res.failure_stage, WriteStage.PRE_REPLACE_CHECK)
        # External content preserved.
        self.assertEqual(target.read_text(), "EXTERNAL")
        # No leftover temp artifacts.
        leftovers = [p for p in self.td.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_atomic_write_if_unchanged_match_replaces(self):
        target = self.td / "direct2.txt"
        target.write_text("original")
        data = b"new content"
        expected = _compute_digest("original")
        res = _atomic_write_if_unchanged(target, data, expected)
        self.assertTrue(res.applied)
        self.assertEqual(target.read_text(), "new content")

    def test_atomic_write_if_unchanged_none_delegates(self):
        target = self.td / "direct3.txt"
        target.write_text("original")
        with mock.patch(
            "core.accept_edits_state._atomic_write", wraps=_atomic_write
        ) as m:
            res = _atomic_write_if_unchanged(target, b"data", None)
            self.assertTrue(res.applied)
            m.assert_called_once()


if __name__ == "__main__":
    unittest.main()
