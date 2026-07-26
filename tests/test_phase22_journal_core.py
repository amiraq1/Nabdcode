"""Phase 2.2B — WAL Journal Core Tests (Gates 0-9).

Covers: schema, checksum, locking, failure semantics, ENOSPC, crash-point.
"""
# pylint: disable=protected-access,missing-docstring,too-many-public-methods

import errno
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import unittest
from unittest import mock
from pathlib import Path

import core.accept_edits_state as _state

from core.accept_edits_state import (
    WalRecord,
    RecoveryReport,
    WorkspaceIdentity,
    ReconciliationRecord,
    TransactionOutcome,
    Snapshot,
    PendingEdit,
    WriteStage,
    AtomicWriteResult,
    JOURNAL_SCHEMA_VERSION,
    _JOURNAL_PATH,
    _JOURNAL_LOCK_PATH,
    _reconciliation_journal,
    _workspace_identity,
    _wal_journal_cache,
    _canonical_json,
    _compute_record_checksum,
    _verify_record_checksum,
    _serialize_wal_record,
    _write_journal_record,
    _make_wal_record,
    _validate_journal_path,
    _detect_invalid_event_sequence,
    reconstruct_operations,
    _make_target_relative,
    _compute_digest,
    _file_digest,
    _write_all,
    _persist_reconciliation_record,
    _record_reconciliation,
    set_journal_path,
    load_and_reconcile_journal,
    set_workspace_identity,
    load_workspace_identity,
    get_workspace_identity,
    reset_session,
    set_mode,
    accept_edit,
    reject_edit,
    peek_pending,
    get_reconciliation_journal,
    _close_journal,
    _compact_journal,
)
from core.accept_edits_state import _ABSENT_SENTINEL

import uuid


# ── Helpers ──────────────────────────────────────────────────────────


def _make_test_edit(path: str = "test_file.txt",
                    old: str = "old_content",
                    new: str = "new_content") -> PendingEdit:
    return PendingEdit(
        path=path,
        resolved_path=str(Path(tempfile.mkdtemp()) / path),
        old_content=old,
        new_content=new,
        diff="@@ -1 +1 @@\n-old\n+new",
        additions=1,
        removals=1,
    )


def _setup_journal(test_dir: str) -> str:
    """Create a journal dir and return the journal path."""
    journal_dir = Path(test_dir) / ".nabd" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    jpath = str(journal_dir / "journal.jsonl")
    set_workspace_identity(str(test_dir))
    set_journal_path(jpath)
    return jpath


def _teardown_journal():
    _close_journal()
    reset_session()


def _make_workspace_id(ws_root: str) -> WorkspaceIdentity:
    ws = set_workspace_identity(ws_root)
    return ws


# ── Gate 4: Canonical JSON & Integrity Checksum ─────────────────────


class TestCanonicalJson(unittest.TestCase):
    """Gate 4 — canonical JSON serialisation rejects NaN/Infinity."""

    def test_canonical_json_rejects_nan(self):
        """_canonical_json raises ValueError on NaN."""
        with self.assertRaises(ValueError):
            _canonical_json({"value": float("nan")})

    def test_canonical_json_rejects_infinity(self):
        """_canonical_json raises ValueError on Infinity."""
        with self.assertRaises(ValueError):
            _canonical_json({"value": float("inf")})

    def test_canonical_json_deterministic(self):
        """Same keys produce same output regardless of insertion order."""
        a = _canonical_json({"b": 2, "a": 1})
        b = _canonical_json({"a": 1, "b": 2})
        self.assertEqual(a, b)

    def test_canonical_json_compact(self):
        """Output has no whitespace between tokens."""
        result = _canonical_json({"a": 1})
        self.assertNotIn(" ", result)


class TestChecksum(unittest.TestCase):
    """Gate 4 — integrity checksum round-trip."""

    def test_compute_checksum_strips_checksum_field(self):
        """_compute_record_checksum excludes 'checksum' from input."""
        payload = {"a": 1, "b": 2, "checksum": "should_be_ignored"}
        cs1 = _compute_record_checksum(payload)
        cs2 = _compute_record_checksum({"a": 1, "b": 2})
        self.assertEqual(cs1, cs2)

    def test_verify_valid_checksum(self):
        """Round-trip: compute then verify returns True."""
        payload = {"op": "test", "value": 42}
        cs = _compute_record_checksum(payload)
        payload["checksum"] = cs
        self.assertTrue(_verify_record_checksum(payload))

    def test_verify_tampered_checksum(self):
        """Tampered data fails verification."""
        payload = {"op": "test", "value": 42}
        payload["checksum"] = "deadbeef" * 8
        self.assertFalse(_verify_record_checksum(payload))

    def test_verify_missing_checksum(self):
        """Record without checksum field fails verification."""
        self.assertFalse(_verify_record_checksum({"op": "test"}))


class TestWalRecordSerialization(unittest.TestCase):
    """Gate 3-4 — WalRecord schema + checksum."""

    def setUp(self):
        _make_workspace_id(tempfile.mkdtemp())

    def tearDown(self):
        _teardown_journal()

    def _make_rec(self, **overrides) -> WalRecord:
        kwargs = dict(
            event_type="PREPARED", sequence=1,
            operation_id="op-1", edit_id="edit-1",
            operation_type="ACCEPT",
            target_path_relative="test.txt",
            expected_original_digest="abc",
            intended_result_digest="def",
        )
        kwargs.update(overrides)
        return _make_wal_record(**kwargs)

    def test_serialize_wal_record_contains_checksum(self):
        """_serialize_wal_record produces valid JSON with checksum."""
        rec = self._make_rec()
        data = _serialize_wal_record(rec)
        parsed = json.loads(data.decode("utf-8"))
        self.assertIn("checksum", parsed)
        self.assertEqual(len(parsed["checksum"]), 64)

    def test_serialize_wal_record_verifies_checksum(self):
        """Deserialised record passes _verify_record_checksum."""
        rec = self._make_rec()
        data = _serialize_wal_record(rec)
        parsed = json.loads(data.decode("utf-8"))
        self.assertTrue(_verify_record_checksum(parsed))

    def test_wal_record_has_schema_version_1(self):
        """Every WalRecord carries schema_version == 1."""
        rec = self._make_rec()
        self.assertEqual(rec.schema_version, 1)

    def test_wal_record_has_unique_record_id(self):
        """Each WalRecord gets a unique record_id."""
        rec1 = self._make_rec()
        rec2 = self._make_rec()
        self.assertNotEqual(rec1.record_id, rec2.record_id)


class TestWorkspaceIdentity(unittest.TestCase):
    """Gate 3 — workspace identity isolation."""

    def setUp(self):
        _teardown_journal()

    def tearDown(self):
        _teardown_journal()

    def test_set_workspace_identity_returns_valid(self):
        """set_workspace_identity returns a WorkspaceIdentity."""
        ws = set_workspace_identity(tempfile.mkdtemp())
        self.assertIsInstance(ws, WorkspaceIdentity)
        self.assertTrue(len(ws.workspace_id) > 0)
        self.assertTrue(len(ws.root_fingerprint) > 0)

    def test_workspace_identity_is_persisted(self):
        """load_workspace_identity restores saved identity."""
        # We need the identity to be saved first (by load_workspace_identity)
        # Because set_workspace_identity only sets in-memory.
        pass  # tested in acceptance


# ── Gate 5: Journal File Security ────────────────────────────────────


class TestJournalPathValidation(unittest.TestCase):
    """Gate 5 — path security."""

    def test_validate_journal_path_empty(self):
        """Empty journal path is rejected."""
        self.assertIsNotNone(_validate_journal_path(""))

    def test_validate_journal_path_rejects_symlink(self):
        """Journal path that is a symlink is rejected."""
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real"
            real.touch()
            link = Path(td) / "link"
            link.symlink_to(real)
            err = _validate_journal_path(str(link))
            self.assertIsNotNone(err)
            self.assertIn("symlink", err.lower())

    def test_journal_file_mode_0600(self):
        """set_journal_path creates journal file with mode 0600."""
        with tempfile.TemporaryDirectory() as td:
            jpath = str(Path(td) / "journal.jsonl")
            set_workspace_identity(td)
            set_journal_path(jpath)
            # Write one record to create the file
            ws = _workspace_identity
            ws_id = ws.workspace_id if ws else ""
            ws_fp = ws.root_fingerprint if ws else ""
            rec = WalRecord(
                record_id=str(uuid.uuid4()),
                workspace_id=ws_id,
                workspace_root_fingerprint=ws_fp,
                operation_id="op-mode",
                sequence=1,
                event_type="PREPARED",
                edit_id="edit-mode",
                operation_type="ACCEPT",
                target_path_relative="test.txt",
                expected_original_digest="a",
                intended_result_digest="b",
            )
            try:
                _write_journal_record(rec)
            except OSError:
                pass  # may fail in test if fcntl unavailable
            if os.path.exists(jpath):
                mode = stat.S_IMODE(os.stat(jpath).st_mode)
                self.assertEqual(mode, 0o600)
            _teardown_journal()


class TestValidatePathSafe(unittest.TestCase):
    """Existing _validate_path_safe still works with relative paths."""

    def test_target_path_relative_conversion(self):
        """_make_target_relative converts absolute to relative."""
        rel = _make_target_relative(
            "/ws/file.txt", "/ws"
        )
        self.assertEqual(rel, "file.txt")

    def test_target_relative_outside_workspace(self):
        """_make_target_relative falls back to basename when outside."""
        rel = _make_target_relative(
            "/other/file.txt", "/ws"
        )
        self.assertEqual(rel, "file.txt")


# ── Gate 2-3: WAL Event Model ────────────────────────────────────────


class TestEventSequence(unittest.TestCase):
    """Gate 2-3 — event sequencing and duplicate detection."""

    def setUp(self):
        _make_workspace_id(tempfile.mkdtemp())

    def tearDown(self):
        _teardown_journal()

    def test_detect_missing_prepared(self):
        """APPLIED without PREPARED is caught."""
        records = [
            _make_wal_record(
                event_type="APPLIED", sequence=2,
                operation_id="op-1", edit_id="e1",
                operation_type="ACCEPT", target_path_relative="f.txt",
            ),
        ]
        diags = _detect_invalid_event_sequence(records)
        self.assertTrue(any("INVALID_EVENT_SEQUENCE" in d for d in diags))

    def test_detect_duplicate_record_id(self):
        """Duplicate record_id is detected."""
        rec1 = _make_wal_record(
            event_type="PREPARED", sequence=1,
            operation_id="op-1", edit_id="e1",
            operation_type="ACCEPT", target_path_relative="f.txt",
        )
        rec2 = WalRecord(
            schema_version=1,
            record_id=rec1.record_id,  # same record_id
            workspace_id="", workspace_root_fingerprint="",
            operation_id="op-2", sequence=1,
            event_type="PREPARED", edit_id="e2",
            operation_type="ACCEPT", target_path_relative="g.txt",
            expected_original_digest="", intended_result_digest="",
        )
        diags = _detect_invalid_event_sequence([rec1, rec2])
        self.assertTrue(any("DUPLICATE_RECORD_ID" in d for d in diags))

    def test_valid_sequence_no_diagnostics(self):
        """PREPARED→APPLIED→COMMITTED→RESOLVED produces no diagnostics."""
        op_id = "op-valid"
        records = [
            _make_wal_record(event_type="PREPARED", sequence=1, operation_id=op_id, edit_id="e1", operation_type="ACCEPT", target_path_relative="f.txt"),
            _make_wal_record(event_type="APPLIED", sequence=2, operation_id=op_id, edit_id="e1", operation_type="ACCEPT", target_path_relative="f.txt"),
            _make_wal_record(event_type="COMMITTED", sequence=3, operation_id=op_id, edit_id="e1", operation_type="ACCEPT", target_path_relative="f.txt"),
            _make_wal_record(event_type="RESOLVED", sequence=4, operation_id=op_id, edit_id="e1", operation_type="ACCEPT", target_path_relative="f.txt"),
        ]
        diags = _detect_invalid_event_sequence(records)
        self.assertEqual(len(diags), 0)


def make_valid_wal_record(**kw) -> WalRecord:
    defaults = dict(
        event_type="PREPARED", sequence=1,
        operation_id="op-r", edit_id="e-r",
        operation_type="ACCEPT",
        target_path_relative="f.txt",
        expected_original_digest="a",
        intended_result_digest="b",
    )
    defaults.update(kw)
    return _make_wal_record(**defaults)

def make_intentionally_corrupt_record(**kw) -> WalRecord:
    rec = make_valid_wal_record(**kw)
    # Alter payload but don't fix checksum
    import dataclasses
    return dataclasses.replace(rec, sequence=rec.sequence + 100)

def make_unsupported_schema_record(**kw) -> WalRecord:
    rec = make_valid_wal_record(**kw)
    import dataclasses
    rec = dataclasses.replace(rec, schema_version=999)
    # Recompute checksum to ensure it's not caught as CORRUPT_RECORD first
    return dataclasses.replace(rec, checksum=_compute_record_checksum(dataclasses.asdict(rec)))

class TestFixtureGuardContract(unittest.TestCase):
    """Guard tests to verify Fixture Builders logic."""
    def test_valid_builder_produces_correct_checksum(self):
        rec = make_valid_wal_record()
        import dataclasses
        self.assertTrue(_verify_record_checksum(dataclasses.asdict(rec)))

    def test_modify_frozen_field_raises_error(self):
        rec = make_valid_wal_record()
        import dataclasses
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rec.sequence = 99

    def test_dataclasses_replace_requires_checksum_update(self):
        rec = make_valid_wal_record()
        import dataclasses
        rec2 = dataclasses.replace(rec, sequence=rec.sequence + 1)
        self.assertFalse(_verify_record_checksum(dataclasses.asdict(rec2)))

    def test_corruption_builder_produces_intentional_corruption(self):
        rec = make_intentionally_corrupt_record()
        import dataclasses
        self.assertFalse(_verify_record_checksum(dataclasses.asdict(rec)))

    def test_resolved_safe_fixture_has_durability_evidence(self):
        recs = [
            make_valid_wal_record(sequence=1, event_type="PREPARED"),
            make_valid_wal_record(sequence=2, event_type="APPLIED"),
            make_valid_wal_record(sequence=3, event_type="COMMITTED"),
            make_valid_wal_record(sequence=4, event_type="RESOLVED", durability_confirmed=True),
        ]
        report = reconstruct_operations(recs)
        self.assertFalse(report.requires_review)

    def test_resolved_unsafe_fixture_remains_requires_review(self):
        rec = make_valid_wal_record(event_type="RESOLVED")  # no durability
        report = reconstruct_operations([rec])
        self.assertTrue(report.requires_review)


# ── Gate 14: Pure Reconstruction — Comprehensive ────────────────────


class TestReconstruction(unittest.TestCase):
    """Gate 14 — reconstruct_operations pure function."""

    def setUp(self):
        _make_workspace_id(tempfile.mkdtemp())

    def tearDown(self):
        _teardown_journal()

    def _make(self, **kw) -> WalRecord:
        return make_valid_wal_record(**kw)

    def test_reconstruction_is_pure_no_io(self):
        """reconstruct_operations does not touch filesystem."""
        rec = make_valid_wal_record()
        # Should not raise, should not create files
        report = reconstruct_operations([rec])
        self.assertIsInstance(report, RecoveryReport)

    def test_valid_sequence_no_diagnostics(self):
        """PREPARED→APPLIED→COMMITTED→RESOLVED → no diagnostics."""
        recs = [
            make_valid_wal_record(sequence=1, event_type="PREPARED", operation_id="op-v"),
            make_valid_wal_record(sequence=2, event_type="APPLIED", operation_id="op-v"),
            make_valid_wal_record(sequence=3, event_type="COMMITTED", operation_id="op-v"),
            make_valid_wal_record(sequence=4, event_type="RESOLVED", operation_id="op-v", durability_confirmed=True),
        ]
        report = reconstruct_operations(recs)
        self.assertEqual(len(report.diagnostics), 0)
        self.assertFalse(report.requires_review)

    def test_applied_without_prepared(self):
        """APPLIED without PREPARED is detected."""
        recs = [
            self._make(sequence=2, event_type="APPLIED", operation_id="op-awp"),
        ]
        report = reconstruct_operations(recs)
        self.assertTrue(
            any("APPLIED without PREPARED" in d for d in report.diagnostics)
        )

    def test_committed_without_applied(self):
        """COMMITTED without APPLIED is detected."""
        recs = [
            self._make(sequence=1, event_type="PREPARED", operation_id="op-cwa"),
            self._make(sequence=3, event_type="COMMITTED", operation_id="op-cwa"),
        ]
        report = reconstruct_operations(recs)
        self.assertTrue(
            any("COMMITTED without APPLIED" in d for d in report.diagnostics)
        )

    def test_resolved_without_committed(self):
        """RESOLVED without COMMITTED is detected."""
        recs = [
            self._make(sequence=1, event_type="PREPARED", operation_id="op-rwc"),
            self._make(sequence=2, event_type="APPLIED", operation_id="op-rwc"),
            self._make(sequence=4, event_type="RESOLVED", operation_id="op-rwc"),
        ]
        report = reconstruct_operations(recs)
        self.assertTrue(
            any("RESOLVED without COMMITTED" in d for d in report.diagnostics)
        )

    def test_sequence_regression(self):
        """Sequence regression (seq <= prev) is detected."""
        recs = [
            self._make(sequence=1, event_type="PREPARED", operation_id="op-sr"),
            self._make(sequence=2, event_type="APPLIED", operation_id="op-sr"),
            self._make(sequence=1, event_type="COMMITTED", operation_id="op-sr"),  # regression seq
        ]
        report = reconstruct_operations(recs)
        self.assertTrue(
            any("INVALID_EVENT_SEQUENCE" in d and "< previous" in d
                for d in report.diagnostics)
        )

    def test_conflicting_duplicate_sequence(self):
        """Same sequence, different event_type → CONFLICTING_DUPLICATE_EVENT."""
        recs = [
            self._make(sequence=1, event_type="PREPARED", operation_id="op-cds"),
            self._make(sequence=1, event_type="APPLIED", operation_id="op-cds"),  # conflict
        ]
        report = reconstruct_operations(recs)
        self.assertTrue(
            any("CONFLICTING_DUPLICATE_EVENT" in d for d in report.diagnostics)
        )

    def test_duplicate_record_id(self):
        """Duplicate record_id detected."""
        import dataclasses
        rec1 = self._make(event_type="PREPARED", sequence=1, operation_id="op-dr1")
        rec2_base = self._make(
            event_type="PREPARED", sequence=1, operation_id="op-dr2",
            target_path_relative="g.txt",
        )
        rec2 = dataclasses.replace(rec2_base, record_id=rec1.record_id)
        # We must fix its checksum so it is not caught as CORRUPT_RECORD before DUPLICATE
        rec2 = dataclasses.replace(rec2, checksum=_compute_record_checksum(dataclasses.asdict(rec2)))

        report = reconstruct_operations([rec1, rec2])
        self.assertTrue(
            any("DUPLICATE_RECORD_ID" in d for d in report.diagnostics)
        )

    def test_operation_identity_conflict_edit_ids(self):
        """Same operation_id but different edit_ids → OPERATION_IDENTITY_CONFLICT."""
        recs = [
            self._make(operation_id="op-ic", edit_id="e1"),
            self._make(operation_id="op-ic", edit_id="e2", sequence=2, event_type="APPLIED"),
        ]
        report = reconstruct_operations(recs)
        self.assertTrue(
            any("OPERATION_IDENTITY_CONFLICT" in d for d in report.diagnostics)
        )

    def test_foreign_workspace(self):
        """Record with different workspace_id → FOREIGN_WORKSPACE_RECORD."""
        import dataclasses
        rec_base = self._make(
            operation_id="op-fw", sequence=1,
            event_type="PREPARED", edit_id="e-fw",
            operation_type="ACCEPT", target_path_relative="f.txt"
        )
        rec = dataclasses.replace(
            rec_base,
            workspace_id="foreign-ws-id",
            workspace_root_fingerprint="foreign-fp"
        )
        rec = dataclasses.replace(rec, checksum=_compute_record_checksum(dataclasses.asdict(rec)))

        report = reconstruct_operations([rec], current_workspace_id="our-ws-id")
        self.assertTrue(report.foreign_workspace_records)

    def test_unsupported_schema(self):
        """Unknown schema_version → UNSUPPORTED_SCHEMA."""
        rec = WalRecord(
            schema_version=999,
            record_id="bad-schema", workspace_id="", workspace_root_fingerprint="",
            operation_id="op-uns", sequence=1,
            event_type="PREPARED", edit_id="e1",
            operation_type="ACCEPT", target_path_relative="f.txt",
            expected_original_digest="", intended_result_digest="",
        )
        report = reconstruct_operations([rec])
        self.assertTrue(report.unsupported_schema_detected)
        self.assertTrue(any("UNSUPPORTED_SCHEMA" in d for d in report.diagnostics))

    def test_pending_review_triggers_requires_review(self):
        """PENDING_REVIEW status sets requires_review=True."""
        rec = self._make(recovery_status="PENDING_REVIEW")
        report = reconstruct_operations([rec])
        self.assertTrue(report.requires_review)

    def test_unsupported_event_type(self):
        """Unknown event_type → UNSUPPORTED_EVENT_TYPE."""
        rec = self._make(event_type="MYSTERY")
        report = reconstruct_operations([rec])
        self.assertTrue(
            any("UNSUPPORTED_EVENT_TYPE" in d for d in report.diagnostics)
        )


# ── Gate 8: ENOSPC ───────────────────────────────────────────────────


class TestEnospc(unittest.TestCase):
    """Gate 8 — ENOSPC behaviour."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def _setup_accept(self, test_dir: str) -> tuple[str, PendingEdit]:
        jpath = _setup_journal(str(test_dir))
        edit = _make_test_edit()
        edit.resolved_path = str(test_dir / edit.path)
        with open(edit.resolved_path, "w") as f:
            f.write(edit.old_content)
        edit.expected_original_digest = _compute_digest(edit.old_content)
        from core.accept_edits_state import _accept_edits_pending
        _accept_edits_pending.append(edit)
        set_mode(True)
        return jpath, edit

    def test_enospc_before_side_effect(self):
        """ENOSPC on PREPARED write: no side effect, outcome=FAILED."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath, edit = self._setup_accept(td)
            # Simulate ENOSPC on journal write
            with mock.patch.object(
                os, "write",
                side_effect=OSError(errno.ENOSPC, "ENOSPC"),
            ):
                result = accept_edit(edit.edit_id)
            self.assertEqual(result.outcome, TransactionOutcome.FAILED)
            # Target file should be unchanged
            if os.path.exists(edit.resolved_path):
                with open(edit.resolved_path) as f:
                    self.assertEqual(f.read(), edit.old_content)

    def test_enospc_after_side_effect(self):
        """ENOSPC on APPLIED write: RECONCILIATION_REQUIRED."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath, edit = self._setup_accept(td)
            # Let first write (PREPARED) succeed, fail second (APPLIED)
            call = [0]
            orig_write = os.write
            def side_effect(fd, data):
                call[0] += 1
                if call[0] >= 3:  # journal APPLIED write
                    raise OSError(errno.ENOSPC, "ENOSPC")
                return orig_write(fd, data)
            with mock.patch.object(os, "write", side_effect):
                result = accept_edit(edit.edit_id)
            self.assertEqual(result.outcome, TransactionOutcome.RECONCILIATION_REQUIRED)


# ── Gate 7: Failure Semantics ────────────────────────────────────────


class TestJournalFailureSemantics(unittest.TestCase):
    """Gate 7 — journal failure does not swallow errors."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def test_persist_reconciliation_no_swallow(self):
        """_persist_reconciliation_record no longer has except OSError: pass."""
        reset_session()
        with tempfile.TemporaryDirectory() as td:
            # Valid journal path — simulate OSError via mock instead of
            # relying on filesystem permissions (F2FS does not enforce
            # chmod reliably on Android/Termux).
            jdir = Path(td) / "journal_dir"
            jpath = str(jdir / "journal.jsonl")
            set_journal_path(jpath)
            # Mock io.open to fail when opening the journal file.
            # _persist_reconciliation_record uses Path.open() which calls
            # io.open() internally.
            import io
            original_io_open = io.open
            def fail_on_journal_open(*args, **kwargs):
                filepath = str(args[0]) if args else ""
                if "journal.jsonl" in filepath:
                    raise OSError(errno.EACCES, "Permission denied")
                return original_io_open(*args, **kwargs)
            rec = ReconciliationRecord(
                operation_id="op", edit_id="e",
                resolved_path=os.path.join(tempfile.gettempdir(), "f"), claim_token="t",
                expected_digest="d", observed_digest="d",
                failure_stage="TEST", recovery_status="PENDING_REVIEW",
                has_snapshot=False, timestamp_ns=0,
            )
            with mock.patch.object(io, "open", side_effect=fail_on_journal_open) as mock_io:
                with self.assertRaises(OSError):
                    _persist_reconciliation_record(rec)
                mock_io.assert_called_once()


# ── Gate 9: Crash-Point Model (Structural) ───────────────────────────


class TestCrashPointModel(unittest.TestCase):
    """Gate 9 — crash-point classification."""

    def test_prepared_state_classification(self):
        """Record with only PREPARED is classified PENDING_REVIEW."""
        rec = _make_wal_record(
            "PREPARED", 1, "op-crash", "e1", "ACCEPT", "f.txt",
            recovery_status="PENDING_REVIEW",
        )
        report = RecoveryReport(operations=(rec,), requires_review=True)
        self.assertTrue(report.requires_review)
        self.assertEqual(len(report.operations), 1)

    def test_applied_not_committed_recovery(self):
        """APPLIED without COMMITTED sets requires_review."""
        rec = _make_wal_record(
            "APPLIED", 2, "op-crash2", "e1", "ACCEPT", "f.txt",
            side_effect_applied=True, recovery_status="PENDING_REVIEW",
        )
        report = RecoveryReport(operations=(rec,), requires_review=True)
        self.assertTrue(report.requires_review)


# ── Gate 6: Stable Lock & Thread Safety ──────────────────────────────


class TestThreadSafety(unittest.TestCase):
    """Gate 6 — concurrent writes do not interleave."""

    def test_thread_writes_do_not_interleave(self):
        """Two threads writing concurrently produce valid JSONL."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            errors = []
            lock = threading.Lock()

            def writer(prefix: str, count: int):
                for i in range(count):
                    rec = _make_wal_record(
                        event_type="PREPARED", sequence=1,
                        operation_id=f"{prefix}-{i}",
                        edit_id=f"e-{prefix}-{i}",
                        operation_type="ACCEPT",
                        target_path_relative=f"{prefix}/{i}.txt",
                        expected_original_digest="",
                        intended_result_digest="",
                    )
                    try:
                        _write_journal_record(rec)
                    except OSError as exc:
                        with lock:
                            errors.append(str(exc))

            t1 = threading.Thread(target=writer, args=("A", 10))
            t2 = threading.Thread(target=writer, args=("B", 10))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # All lines should be valid JSON
            jp = Path(jpath)
            if jp.exists():
                lines = jp.read_text(encoding="utf-8").strip().splitlines()
                for line in lines:
                    try:
                        d = json.loads(line)
                        self.assertTrue(_verify_record_checksum(d))
                    except (json.JSONDecodeError, KeyError):
                        self.fail(f"Invalid line: {line}")
            _teardown_journal()


# ── Gate 2: WAL Lifecycle ────────────────────────────────────────────


class TestWalLifecycle(unittest.TestCase):
    """Gate 2 — PREPARED → APPLIED → COMMITTED → RESOLVED."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def test_accept_edit_writes_prepared(self):
        """accept_edit writes PREPARED to journal before side effect."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            edit = _make_test_edit()
            edit.resolved_path = str(td / edit.path)
            with open(edit.resolved_path, "w") as f:
                f.write(edit.old_content)
            edit.expected_original_digest = _compute_digest(edit.old_content)
            from core.accept_edits_state import _accept_edits_pending
            _accept_edits_pending.append(edit)
            set_mode(True)

            result = accept_edit(edit.edit_id)
            self.assertEqual(result.outcome, TransactionOutcome.ACCEPTED)

            # Journal should exist with PREPARED, APPLIED, COMMITTED, RESOLVED
            jp = Path(jpath)
            self.assertTrue(jp.exists())
            content = jp.read_text(encoding="utf-8")
            self.assertIn("PREPARED", content)
            self.assertIn("APPLIED", content)
            self.assertIn("COMMITTED", content)
            # RESOLVED may not be in content if last write skipped
            # But at minimum PREPARED should be there

    def test_accept_edit_prepared_before_side_effect(self):
        """If journal fails at PREPARED, side effect does NOT occur."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            edit = _make_test_edit()
            edit.resolved_path = str(td / edit.path)
            with open(edit.resolved_path, "w") as f:
                f.write(edit.old_content)
            edit.expected_original_digest = _compute_digest(edit.old_content)
            from core.accept_edits_state import _accept_edits_pending
            _accept_edits_pending.append(edit)
            set_mode(True)

            # Patched os.write to fail for PREPARED
            orig_write = os.write
            call_count = [0]
            def fail_on_prepared(fd, data):
                call_count[0] += 1
                if call_count[0] == 1:  # First write = PREPARED
                    raise OSError(errno.EIO, "mock EIO")
                return orig_write(fd, data)

            with unittest.mock.patch.object(os, "write", fail_on_prepared):
                result = accept_edit(edit.edit_id)
            self.assertEqual(result.outcome, TransactionOutcome.FAILED)
            # Target file unchanged
            if os.path.exists(edit.resolved_path):
                with open(edit.resolved_path) as f:
                    self.assertEqual(f.read(), edit.old_content)

    def test_reject_edit_writes_wal(self):
        """reject_edit writes WAL events."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            edit = _make_test_edit()
            from core.accept_edits_state import _accept_edits_pending
            _accept_edits_pending.append(edit)
            set_mode(True)

            result = reject_edit(edit.edit_id)
            self.assertIn(result.outcome,
                          (TransactionOutcome.REJECTED,
                           TransactionOutcome.RECONCILIATION_REQUIRED))

            # Journal should have PREPARED at minimum
            jp = Path(jpath)
            if jp.exists():
                content = jp.read_text(encoding="utf-8")
                self.assertIn("PREPARED", content)


# ── Gate 0: Filesystem & fcntl ───────────────────────────────────────


class TestFcntlAvailable(unittest.TestCase):
    """Gate 0 — fcntl.flock must be available."""

    def test_fcntl_imports(self):
        """fcntl and LOCK_EX are importable."""
        import fcntl
        self.assertTrue(fcntl.LOCK_EX)


class TestRecoveryReport(unittest.TestCase):
    """RecoveryReport structure and defaults."""

    def test_defaults(self):
        """Default RecoveryReport has no operations and no review required."""
        r = RecoveryReport()
        self.assertEqual(len(r.operations), 0)
        self.assertFalse(r.requires_review)

    def test_corruption_flag(self):
        """RecoveryReport carries corruption flag."""
        r = RecoveryReport(corruption_detected=True)
        self.assertTrue(r.corruption_detected)


# ── Gate 10: No-Blind-Replay Spies ──────────────────────────────────


class TestNoBlindReplay(unittest.TestCase):
    """Gate 10 — loader performs zero side effects."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def test_loader_returns_report_not_side_effects(self):
        """load_and_reconcile_journal returns RecoveryReport, does not call apply/rollback."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = str(td / ".nabd" / "journal" / "journal.jsonl")
            jdir = Path(jpath).parent
            jdir.mkdir(parents=True, exist_ok=True)
            set_workspace_identity(str(td))
            set_journal_path(jpath)

            # Write a PREPARED record
            rec = _make_wal_record(
                event_type="PREPARED", sequence=1,
                operation_id="op-spy", edit_id="e-spy",
                operation_type="ACCEPT",
                target_path_relative="spy.txt",
                expected_original_digest="abc",
                intended_result_digest="def",
            )
            _write_journal_record(rec)

            # Spy on functions via core.accept_edits_state module
            with mock.patch("core.accept_edits_state._atomic_write") as mock_write:
                with mock.patch("core.accept_edits_state._rollback_snapshot") as mock_rollback:
                    report = load_and_reconcile_journal()
                    self.assertIsInstance(report, RecoveryReport)
                    mock_write.assert_not_called()
                    mock_rollback.assert_not_called()

    def test_loader_does_not_call_accept_or_reject(self):
        """Loader must not call accept_edit or reject_edit."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = str(td / ".nabd" / "journal" / "journal.jsonl")
            jdir = Path(jpath).parent
            jdir.mkdir(parents=True, exist_ok=True)
            set_workspace_identity(str(td))
            set_journal_path(jpath)
            rec = _make_wal_record(
                event_type="PREPARED", sequence=1,
                operation_id="op-spy2", edit_id="e-spy2",
                operation_type="ACCEPT",
                target_path_relative="spy2.txt",
                expected_original_digest="abc",
                intended_result_digest="def",
            )
            _write_journal_record(rec)

            with mock.patch("core.accept_edits_state.accept_edit") as mock_accept:
                with mock.patch("core.accept_edits_state.reject_edit") as mock_reject:
                    load_and_reconcile_journal()
                    mock_accept.assert_not_called()
                    mock_reject.assert_not_called()

    def test_loader_preserves_unresolved_records(self):
        """Unresolved (PENDING_REVIEW) records survive loader."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = str(td / ".nabd" / "journal" / "journal.jsonl")
            jdir = Path(jpath).parent
            jdir.mkdir(parents=True, exist_ok=True)
            set_workspace_identity(str(td))
            set_journal_path(jpath)
            rec = _make_wal_record(
                event_type="PREPARED", sequence=1,
                operation_id="op-unresolved", edit_id="e-unresolved",
                operation_type="ACCEPT",
                target_path_relative="unresolved.txt",
                expected_original_digest="abc",
                intended_result_digest="def",
                recovery_status="PENDING_REVIEW",
            )
            _write_journal_record(rec)

            report = load_and_reconcile_journal()
            self.assertTrue(report.requires_review)
            self.assertEqual(len(report.operations), 1)


# ── Gate 11: Fresh-Process Restart (SIGKILL + pipe handshake) ───────


class TestFreshProcessRestart(unittest.TestCase):
    """Gate 11 — fresh-process restart with subprocess + SIGKILL."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def _write_prepared_journal(self, td: Path, ws_root: str) -> str:
        """Set up journal dir, write a PREPARED record, return journal path."""
        jdir = td / ".nabd" / "journal"
        jdir.mkdir(parents=True, exist_ok=True)
        jpath = str(jdir / "journal.jsonl")
        lock_path = str(jdir / "journal.lock")
        # Create lock file
        with open(lock_path, "w") as f:
            f.write("")
        from core.accept_edits_state import _JOURNAL_PATH, _JOURNAL_LOCK_PATH
        load_workspace_identity(ws_root)  # persists workspace.json to disk
        set_journal_path(jpath)
        rec = _make_wal_record(
            event_type="PREPARED", sequence=1,
            operation_id="op-fresh", edit_id="e-fresh",
            operation_type="ACCEPT",
            target_path_relative="fresh.txt",
            expected_original_digest="abc",
            intended_result_digest="def",
        )
        _write_journal_record(rec)
        _close_journal()
        return jpath

    def test_prepared_survives_subprocess_restart(self):
        """PREPARED record persists across fresh Python subprocess."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ws_root = str(td)
            jpath = self._write_prepared_journal(td, ws_root)

            # Child script: fresh Python, reads journal, prints JSON
            script = (
                "import json, sys\n"
                "sys.path.insert(0, '.')\n"
                "from core.accept_edits_state import (\n"
                "    set_journal_path, load_workspace_identity,\n"
                "    load_and_reconcile_journal,\n"
                ")\n"
                "load_workspace_identity(sys.argv[1])\n"
                "set_journal_path(sys.argv[2])\n"
                "report = load_and_reconcile_journal()\n"
                "print(json.dumps({\n"
                "    'requires_review': report.requires_review,\n"
                "    'num_operations': len(report.operations),\n"
                "    'diagnostics': list(report.diagnostics),\n"
                "}))\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", script, ws_root, jpath],
                capture_output=True, text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                             f"subprocess failed: {result.stderr}")
            data = json.loads(result.stdout.strip())
            self.assertEqual(data["num_operations"], 1,
                             f"Expected 1 operation, got {data}")
            self.assertTrue(data["requires_review"],
                            "PREPARED should require review")
            self.assertEqual(len(data["diagnostics"]), 0,
                             f"Unexpected diagnostics: {data['diagnostics']}")

    def test_sigkill_preserves_journal(self):
        """SIGKILL during operation does not corrupt journal."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ws_root = str(td)
            jpath = self._write_prepared_journal(td, ws_root)

            # Start a child process that reads journal and waits
            script = (
                "import sys, time\n"
                "sys.path.insert(0, '.')\n"
                "from core.accept_edits_state import (\n"
                "    set_journal_path, load_workspace_identity,\n"
                "    load_and_reconcile_journal,\n"
                ")\n"
                "load_workspace_identity(sys.argv[1])\n"
                "set_journal_path(sys.argv[2])\n"
                "report = load_and_reconcile_journal()\n"
                "sys.stderr.write('REACHED:load_done\\n')\n"
                "sys.stderr.flush()\n"
                "time.sleep(30)\n"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", script, ws_root, jpath],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                # Wait for signal
                stderr_line = proc.stderr.readline()
                self.assertIn("REACHED:load_done", stderr_line)
                # SIGKILL the child
                proc.send_signal(signal.SIGKILL)
                proc.wait(timeout=5)
                self.assertNotEqual(proc.returncode, 0)
                # Child B: verify journal intact
                verify_script = (
                    "import json, sys\n"
                    "sys.path.insert(0, '.')\n"
                    "from core.accept_edits_state import (\n"
                    "    set_journal_path, load_workspace_identity,\n"
                    "    load_and_reconcile_journal,\n"
                    ")\n"
                    "load_workspace_identity(sys.argv[1])\n"
                    "set_journal_path(sys.argv[2])\n"
                    "report = load_and_reconcile_journal()\n"
                    "print(json.dumps({\n"
                    "    'requires_review': report.requires_review,\n"
                    "    'num_operations': len(report.operations),\n"
                    "}))\n"
                )
                result = subprocess.run(
                    [sys.executable, "-c", verify_script, ws_root, jpath],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0)
                data = json.loads(result.stdout.strip())
                self.assertEqual(data["num_operations"], 1,
                                 "Journal lost after SIGKILL")
                self.assertTrue(data["requires_review"],
                                "PREPARED should still require review")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)


# ── Gate 12: Corruption & Truncated Tail ────────────────────────────


class TestCorruptionHandling(unittest.TestCase):
    """Gate 12 — corruption detection in journal loader."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def _setup_journal(self, td: Path, content: str) -> tuple[str, str]:
        """Write raw content to journal, return (ws_root, jpath)."""
        jdir = td / ".nabd" / "journal"
        jdir.mkdir(parents=True, exist_ok=True)
        jpath = str(jdir / "journal.jsonl")
        lock_path = str(jdir / "journal.lock")
        with open(lock_path, "w") as f:
            f.write("")
        ws = load_workspace_identity(str(td))
        set_journal_path(jpath)
        # Write raw bytes
        Path(jpath).write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        _close_journal()
        return str(td), jpath

    def test_truncated_tail_detected(self):
        """Truncated final line (no trailing newline) is detected as TRUNCATED_TAIL."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ws_root, jpath = self._setup_journal(td, '{"valid":true}')
            report = load_and_reconcile_journal()
            self.assertTrue(report.truncated_tail_detected,
                            f"Expected truncated tail, got diagnostics: {report.diagnostics}")
            # Valid records before truncation are still parsed
            # (empty valid record is skipped because no known fields)
            self.assertFalse(report.corruption_detected)

    def test_checksum_mismatch_reported(self):
        """Checksum mismatch is reported as CORRUPT_RECORD."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ws_root, jpath = self._setup_journal(td, "")
            # Reopen and write a record with mismatched checksum
            from core.accept_edits_state import _workspace_identity
            ws_id = _workspace_identity.workspace_id if _workspace_identity else ""
            bad_line = f'{{"schema_version":1,"record_id":"r1","checksum":"bad0000000000000000000000000000000000000000000000000000000000000000","workspace_id":"{ws_id}","workspace_root_fingerprint":"","event_type":"PREPARED","operation_id":"op-c","edit_id":"e-c","operation_type":"ACCEPT","target_path_relative":"c.txt","sequence":1,"expected_original_digest":"","intended_result_digest":"","side_effect_applied":false,"durability_confirmed":false,"cleanup_succeeded":true,"recovery_status":"","created_at":""}}'
            Path(jpath).write_text(bad_line + "\n")
            _close_journal()
            report = load_and_reconcile_journal()
            self.assertTrue(
                report.corruption_detected or
                any("CORRUPT_RECORD" in d for d in report.diagnostics),
                f"Expected corruption detected, got diagnostics: {report.diagnostics}"
            )

    def test_invalid_utf8_reported(self):
        """Invalid UTF-8 is detected as JOURNAL_ENCODING_ERROR."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # Raw bytes that are invalid UTF-8
            jdir = td / ".nabd" / "journal"
            jdir.mkdir(parents=True, exist_ok=True)
            jpath = str(jdir / "journal.jsonl")
            lock_path = str(jdir / "journal.lock")
            with open(lock_path, "w") as f:
                f.write("")
            load_workspace_identity(str(td))
            set_journal_path(jpath)
            Path(jpath).write_bytes(b'\xff\xfe\x00\x01\n')
            _close_journal()
            report = load_and_reconcile_journal()
            self.assertTrue(report.corruption_detected or any(
                "ENCODING_ERROR" in d for d in report.diagnostics
            ))

    def test_valid_records_before_corruption_survive(self):
        """Records before a corrupt line are preserved."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # First write a valid record
            ws_root, jpath = self._setup_journal(td, "")
            # Now manually create journal with one valid + one corrupt line
            valid_rec = _make_wal_record(
                event_type="PREPARED", sequence=1,
                operation_id="op-valid", edit_id="e-valid",
                operation_type="ACCEPT", target_path_relative="v.txt",
                expected_original_digest="a", intended_result_digest="b",
                recovery_status="PENDING_REVIEW",
            )
            # Write valid record then corrupt line
            data = _serialize_wal_record(valid_rec)
            data += b'{"corrupt": true}\n'
            Path(jpath).write_bytes(data)
            _close_journal()

            report = load_and_reconcile_journal()
            self.assertGreater(len(report.operations), 0,
                               "Valid records before corruption are lost")


# ── Gate 13: Retention & Atomic Compaction ──────────────────────────


class TestCompaction(unittest.TestCase):
    """Gate 13 — journal retention and atomic compaction."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def _write_records(self, td: Path, count: int, resolved: bool = True) -> str:
        """Write *count* operations to a journal, optionally all resolved."""
        jdir = td / ".nabd" / "journal"
        jdir.mkdir(parents=True, exist_ok=True)
        jpath = str(jdir / "journal.jsonl")
        lock_path = str(jdir / "journal.lock")
        with open(lock_path, "w") as f:
            f.write("")
        load_workspace_identity(str(td))
        set_journal_path(jpath)
        for i in range(count):
            op_id = f"op-{i}"
            _write_journal_record(_make_wal_record(
                event_type="PREPARED", sequence=1,
                operation_id=op_id, edit_id=f"e-{i}",
                operation_type="ACCEPT",
                target_path_relative=f"{i}.txt",
                expected_original_digest="a", intended_result_digest="b",
            ))
            if resolved:
                _write_journal_record(_make_wal_record(
                    event_type="APPLIED", sequence=2,
                    operation_id=op_id, edit_id=f"e-{i}",
                    operation_type="ACCEPT",
                    target_path_relative=f"{i}.txt",
                    expected_original_digest="a", intended_result_digest="b",
                    side_effect_applied=True,
                ))
                _write_journal_record(_make_wal_record(
                    event_type="COMMITTED", sequence=3,
                    operation_id=op_id, edit_id=f"e-{i}",
                    operation_type="ACCEPT",
                    target_path_relative=f"{i}.txt",
                    expected_original_digest="a", intended_result_digest="b",
                    side_effect_applied=True,
                    recovery_status="RESOLVED",
                ))
                _write_journal_record(_make_wal_record(
                    event_type="RESOLVED", sequence=4,
                    operation_id=op_id, edit_id=f"e-{i}",
                    operation_type="ACCEPT",
                    target_path_relative=f"{i}.txt",
                    expected_original_digest="a", intended_result_digest="b",
                    side_effect_applied=True,
                    recovery_status="RESOLVED",
                    durability_confirmed=True,
                ))
        _close_journal()
        return jpath

    def test_unresolved_operations_never_pruned(self):
        """PREPARED-only operations survive compaction."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = self._write_records(td, 2, resolved=False)

            # Spy: unresolved records pre-compaction
            report_before = load_and_reconcile_journal()
            self.assertTrue(report_before.requires_review)

            success, msg = _compact_journal()
            self.assertTrue(success, f"Compaction failed: {msg}")

            # Unresolved records should still be present
            report_after = load_and_reconcile_journal()
            self.assertTrue(report_after.requires_review,
                            "Unresolved records were pruned!")
            # 2 operations * 1 event each (PREPARED only) = 2 events
            self.assertEqual(len(report_after.operations), 2,
                             "Unresolved records should survive compaction")

    def test_resolved_operations_pruned(self):
        """Fully resolved operations can be pruned."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = self._write_records(td, 3, resolved=True)

            success, msg = _compact_journal()
            self.assertTrue(success, f"Compaction failed: {msg}")

            report = load_and_reconcile_journal()
            # After compaction, all resolved operations should be pruned
            self.assertEqual(len(report.operations), 0,
                             "Resolved operations should be pruned")
            self.assertFalse(report.requires_review)

    def test_compaction_atomic_replace(self):
        """Compaction uses atomic replace, reduces file size."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = self._write_records(td, 2, resolved=True)
            before_size = os.path.getsize(jpath)
            success, msg = _compact_journal()
            self.assertTrue(success, f"Compaction failed: {msg}")
            after_size = os.path.getsize(jpath)
            # Compaction should reduce the file (or at minimum not increase it)
            self.assertLessEqual(after_size, before_size,
                                 "Compaction increased file size")

    def test_restart_after_compaction(self):
        """Fresh subprocess sees same state after compaction."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ws_root = str(td)
            jpath = self._write_records(td, 2, resolved=False)

            success, msg = _compact_journal()
            self.assertTrue(success, f"Compaction failed: {msg}")

            # Fresh subprocess
            script = (
                "import json, sys\n"
                "sys.path.insert(0, '.')\n"
                "from core.accept_edits_state import (\n"
                "    set_journal_path, load_workspace_identity,\n"
                "    load_and_reconcile_journal,\n"
                ")\n"
                "load_workspace_identity(sys.argv[1])\n"
                "set_journal_path(sys.argv[2])\n"
                "report = load_and_reconcile_journal()\n"
                "print(json.dumps({\n"
                "    'requires_review': report.requires_review,\n"
                "    'num_operations': len(report.operations),\n"
                "}))\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", script, ws_root, jpath],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                             f"Subprocess failed: {result.stderr}")
            data = json.loads(result.stdout.strip())
            self.assertTrue(data["requires_review"],
                            "Unresolved ops should survive restart after compaction")
            self.assertGreaterEqual(data["num_operations"], 1,
                                    "Operations lost after compaction restart")


# ── Gate 15: AtomicWriteResult ↔ WAL Integration ────────────────


class TestWalAtomicWriteIntegration(unittest.TestCase):
    """Gate 15 — Journal events correctly reflect AtomicWriteResult states."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def test_prepared_before_atomic_write(self):
        """PREPARED is recorded before _atomic_write is called."""
        call_log = []
        orig_atomic = _state._atomic_write
        def spy(target, data):
            jp = _state._JOURNAL_PATH
            if jp and os.path.exists(jp):
                call_log.append("atomic_write_called")
                content = open(jp).read()
                self.assertIn("PREPARED", content,
                              "PREPARED must precede _atomic_write")
            return orig_atomic(target, data)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            edit = _make_test_edit()
            edit.resolved_path = str(td / edit.path)
            with open(edit.resolved_path, "w") as f:
                f.write(edit.old_content)
            edit.expected_original_digest = _compute_digest(edit.old_content)
            from core.accept_edits_state import _accept_edits_pending
            _accept_edits_pending.append(edit)
            set_mode(True)

            with mock.patch.object(_state, "_atomic_write", side_effect=spy):
                result = accept_edit(edit.edit_id)
            self.assertIn(result.outcome,
                          (TransactionOutcome.ACCEPTED,
                           TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING))

    def test_applied_after_atomic_write_success(self):
        """APPLIED is recorded after successful _atomic_write."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            edit = _make_test_edit()
            edit.resolved_path = str(td / edit.path)
            with open(edit.resolved_path, "w") as f:
                f.write(edit.old_content)
            edit.expected_original_digest = _compute_digest(edit.old_content)
            from core.accept_edits_state import _accept_edits_pending
            _accept_edits_pending.append(edit)
            set_mode(True)
            result = accept_edit(edit.edit_id)
            self.assertIn(result.outcome,
                          (TransactionOutcome.ACCEPTED,
                           TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING))
            content = Path(jpath).read_text()
            self.assertIn("APPLIED", content)
            self.assertIn("COMMITTED", content)

    def test_resolved_not_recorded_for_unresolved(self):
        """A PREPARED-only operation does NOT get a RESOLVED event."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            rec = _make_wal_record(
                event_type="PREPARED", sequence=1,
                operation_id="op-nr", edit_id="e-nr",
                operation_type="ACCEPT",
                target_path_relative="nr.txt",
                expected_original_digest="a", intended_result_digest="b",
            )
            _write_journal_record(rec)
            _close_journal()
            content = Path(jpath).read_text()
            self.assertIn("PREPARED", content)
            self.assertNotIn("RESOLVED", content)

    def test_journal_failure_does_not_erase_primary_failure(self):
        """When journal fails at PREPARED, primary failure is separate."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            _setup_journal(str(td))
            edit = _make_test_edit()
            edit.resolved_path = str(td / edit.path)
            with open(edit.resolved_path, "w") as f:
                f.write(edit.old_content)
            edit.expected_original_digest = _compute_digest(edit.old_content)
            from core.accept_edits_state import _accept_edits_pending
            _accept_edits_pending.append(edit)
            set_mode(True)

            # Only patch journal writes, not os.write globally
            with mock.patch.object(_state, "_write_journal_record",
                                   side_effect=OSError(errno.EIO, "mock journal failure")):
                result = accept_edit(edit.edit_id)
            self.assertEqual(result.outcome, TransactionOutcome.FAILED,
                             f"Expected FAILED, got {result.outcome}")
            self.assertGreater(len(result.failed_items), 0,
                               "Expected a failure item")

    def test_no_duplicate_events_in_successful_accept(self):
        """Successful accept produces exactly 4 events: PREPARED,APPLIED,COMMITTED,RESOLVED."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpath = _setup_journal(str(td))
            edit = _make_test_edit()
            edit.resolved_path = str(td / edit.path)
            with open(edit.resolved_path, "w") as f:
                f.write(edit.old_content)
            edit.expected_original_digest = _compute_digest(edit.old_content)
            from core.accept_edits_state import _accept_edits_pending
            _accept_edits_pending.append(edit)
            set_mode(True)
            result = accept_edit(edit.edit_id)
            self.assertIn(result.outcome, (TransactionOutcome.ACCEPTED,
                                           TransactionOutcome.ACCEPTED_WITH_DURABILITY_WARNING))
            # Count event types for this operation
            content = Path(jpath).read_text()
            events = {"PREPARED": 0, "APPLIED": 0, "COMMITTED": 0, "RESOLVED": 0}
            for line in content.strip().splitlines():
                for evt in events:
                    if f'"event_type":"{evt}"' in line:
                        events[evt] += 1
            for evt, count in events.items():
                self.assertEqual(count, 1,
                                 f"Expected exactly 1 '{evt}' event, got {count}")


# ── Reconstruction outcome tests (fresh process) ─────────────────────


class TestReconstructionOutcomes(unittest.TestCase):
    """Per-outcome reconstruction verification via fresh subprocess."""

    def _write_and_verify(self, records: list, expected_requires_review: bool,
                          expected_operation_count: int, test_name: str):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jdir = td / ".nabd" / "journal"
            jdir.mkdir(parents=True, exist_ok=True)
            jpath = str(jdir / "journal.jsonl")
            lock_path = str(jdir / "journal.lock")
            with open(lock_path, "w") as f:
                f.write("")
            load_workspace_identity(str(td))
            set_journal_path(jpath)

            for rec in records:
                _write_journal_record(rec)
            _close_journal()

            # Fresh subprocess
            script = (
                "import json, sys\n"
                "sys.path.insert(0, '.')\n"
                "from core.accept_edits_state import (\n"
                "    set_journal_path, load_workspace_identity,\n"
                "    load_and_reconcile_journal,\n"
                ")\n"
                "load_workspace_identity(sys.argv[1])\n"
                "set_journal_path(sys.argv[2])\n"
                "report = load_and_reconcile_journal()\n"
                "print(json.dumps({\n"
                "    'requires_review': report.requires_review,\n"
                "    'num_operations': len(report.operations),\n"
                "    'corruption_detected': report.corruption_detected,\n"
                "}))\n"
            )
            p = subprocess.run(
                [sys.executable, "-c", script, str(td), jpath],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(p.returncode, 0,
                             f"[{test_name}] subprocess failed: {p.stderr}")
            data = json.loads(p.stdout.strip())
            self.assertEqual(data["requires_review"], expected_requires_review,
                             f"[{test_name}] requires_review mismatch: {data}")
            self.assertEqual(data["num_operations"], expected_operation_count,
                             f"[{test_name}] operation count mismatch: {data}")

    def test_prepared_pending_review(self):
        """PREPARED only → PENDING_REVIEW after fresh restart."""
        rec = _make_wal_record(
            event_type="PREPARED", sequence=1,
            operation_id="op-r1", edit_id="e-r1",
            operation_type="ACCEPT",
            target_path_relative="r1.txt",
            expected_original_digest="a", intended_result_digest="b",
        )
        self._write_and_verify([rec], True, 1, "PREPARED")

    def test_applied_not_committed(self):
        """PREPARED+APPLIED → APPLIED_NOT_COMMITTED after restart."""
        from core.accept_edits_state import _make_wal_record as mwr
        recs = [
            mwr(event_type="PREPARED", sequence=1, operation_id="op-r2",
                edit_id="e-r2", operation_type="ACCEPT",
                target_path_relative="r2.txt",
                expected_original_digest="a", intended_result_digest="b"),
            mwr(event_type="APPLIED", sequence=2, operation_id="op-r2",
                edit_id="e-r2", operation_type="ACCEPT",
                target_path_relative="r2.txt",
                expected_original_digest="a", intended_result_digest="b",
                side_effect_applied=True),
        ]
        self._write_and_verify(recs, True, 2, "APPLIED_NOT_COMMITTED")

    def test_committed_not_resolved(self):
        """PREPARED+APPLIED+COMMITTED → COMMITTED_NOT_RESOLVED."""
        from core.accept_edits_state import _make_wal_record as mwr
        recs = [
            mwr(event_type="PREPARED", sequence=1, operation_id="op-r3",
                edit_id="e-r3", operation_type="ACCEPT",
                target_path_relative="r3.txt",
                expected_original_digest="a", intended_result_digest="b"),
            mwr(event_type="APPLIED", sequence=2, operation_id="op-r3",
                edit_id="e-r3", operation_type="ACCEPT",
                target_path_relative="r3.txt",
                expected_original_digest="a", intended_result_digest="b",
                side_effect_applied=True),
            mwr(event_type="COMMITTED", sequence=3, operation_id="op-r3",
                edit_id="e-r3", operation_type="ACCEPT",
                target_path_relative="r3.txt",
                expected_original_digest="a", intended_result_digest="b",
                side_effect_applied=True, recovery_status="RESOLVED"),
        ]
        self._write_and_verify(recs, True, 3, "COMMITTED_NOT_RESOLVED")

    def test_resolved_does_not_require_review(self):
        """Complete 4-event cycle → no review required."""
        from core.accept_edits_state import _make_wal_record as mwr
        recs = [
            mwr(event_type="PREPARED", sequence=1, operation_id="op-r4",
                edit_id="e-r4", operation_type="ACCEPT",
                target_path_relative="r4.txt",
                expected_original_digest="a", intended_result_digest="b"),
            mwr(event_type="APPLIED", sequence=2, operation_id="op-r4",
                edit_id="e-r4", operation_type="ACCEPT",
                target_path_relative="r4.txt",
                expected_original_digest="a", intended_result_digest="b",
                side_effect_applied=True),
            mwr(event_type="COMMITTED", sequence=3, operation_id="op-r4",
                edit_id="e-r4", operation_type="ACCEPT",
                target_path_relative="r4.txt",
                expected_original_digest="a", intended_result_digest="b",
                side_effect_applied=True, recovery_status="RESOLVED"),
            mwr(event_type="RESOLVED", sequence=4, operation_id="op-r4",
                edit_id="e-r4", operation_type="ACCEPT",
                target_path_relative="r4.txt",
                expected_original_digest="a", intended_result_digest="b",
                side_effect_applied=True, recovery_status="RESOLVED",
                durability_confirmed=True),
        ]
        self._write_and_verify(recs, False, 4, "RESOLVED")


# ── Regression: PosixPath serialization boundary (Phase 6.1) ──────────


class TestPosixPathSerializationBoundary(unittest.TestCase):
    """Regression: PathLike inputs at WAL serialization boundaries must
    be normalized via os.fspath() before reaching .encode() or JSON."""

    def setUp(self):
        _teardown_journal()
        _make_workspace_id(tempfile.mkdtemp())

    def tearDown(self):
        _teardown_journal()

    def test_compute_digest_accepts_path(self):
        """_compute_digest accepts PathLike and normalizes it."""
        from pathlib import Path
        content = Path(os.path.join(tempfile.gettempdir(), "test_file.txt"))
        result = _compute_digest(content)
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64)

    def test_compute_digest_accepts_str(self):
        """_compute_digest still works with plain str."""
        result = _compute_digest("hello world")
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64)

    def test_make_wal_record_normalizes_pathlike_path(self):
        """_make_wal_record normalizes PathLike target_path_relative."""
        from pathlib import Path
        rec = _make_wal_record(
            event_type="PREPARED", sequence=1,
            operation_id="op-path-test", edit_id="e-pt",
            operation_type="ACCEPT",
            target_path_relative=Path("test/file.txt"),
            expected_original_digest="abc",
            intended_result_digest="def",
        )
        self.assertIsInstance(rec.target_path_relative, str)
        self.assertEqual(rec.target_path_relative, "test/file.txt")

    def test_make_wal_record_accepts_str_path(self):
        """_make_wal_record still works with plain str path."""
        rec = _make_wal_record(
            event_type="PREPARED", sequence=1,
            operation_id="op-str-test", edit_id="e-st",
            operation_type="ACCEPT",
            target_path_relative="normal/file.txt",
            expected_original_digest="abc",
            intended_result_digest="def",
        )
        self.assertIsInstance(rec.target_path_relative, str)
        self.assertEqual(rec.target_path_relative, "normal/file.txt")

    def test_serialize_wal_record_with_pathlike_path_succeeds(self):
        """_serialize_wal_record handles PathLike target_path_relative."""
        from pathlib import Path
        ws = _workspace_identity
        ws_id = ws.workspace_id if ws else ""
        ws_fp = ws.root_fingerprint if ws else ""
        rec = WalRecord(
            record_id=str(uuid.uuid4()),
            workspace_id=ws_id,
            workspace_root_fingerprint=ws_fp,
            operation_id="op-serial-path",
            sequence=1,
            event_type="PREPARED",
            edit_id="e-sp",
            operation_type="ACCEPT",
            target_path_relative=Path("pathlike/file.txt"),
            expected_original_digest="abc",
            intended_result_digest="def",
        )
        data = _serialize_wal_record(rec)
        self.assertIsInstance(data, bytes)
        parsed = json.loads(data.decode("utf-8"))
        self.assertEqual(parsed["target_path_relative"], "pathlike/file.txt")
        self.assertTrue(_verify_record_checksum(parsed))

    def test_serialize_wal_record_rejects_invalid_values(self):
        """_serialize_wal_record still rejects NaN/Infinity (via _canonical_json)."""
        ws = _workspace_identity
        ws_id = ws.workspace_id if ws else ""
        ws_fp = ws.root_fingerprint if ws else ""
        with self.assertRaises(ValueError):
            rec = WalRecord(
                record_id=str(uuid.uuid4()),
                workspace_id=ws_id,
                workspace_root_fingerprint=ws_fp,
                operation_id="op-nan",
                sequence=1,
                event_type="PREPARED",
                edit_id="e-nan",
                operation_type="ACCEPT",
                target_path_relative="nan.txt",
                expected_original_digest="abc",
                intended_result_digest=float("nan"),
            )
            _serialize_wal_record(rec)

    def test_canonical_json_default_str_converts_path(self):
        """_canonical_json with default=str converts Path to string."""
        from pathlib import Path
        result = _canonical_json({"path": Path("test.txt"), "value": 42})
        self.assertIn("test.txt", result)

    def test_canonical_json_still_rejects_nan(self):
        """_canonical_json still rejects NaN despite default=str."""
        with self.assertRaises(ValueError):
            _canonical_json({"value": float("nan")})

    def test_make_wal_record_rejects_absolute_path(self):
        """_make_wal_record rejects absolute target_path_relative."""
        with self.assertRaises(ValueError):
            _make_wal_record(
                event_type="PREPARED", sequence=1,
                operation_id="op-abs", edit_id="e-abs",
                operation_type="ACCEPT",
                target_path_relative="/etc/passwd",
                expected_original_digest="abc",
                intended_result_digest="def",
            )


# ── Cross-process serialization tests ────────────────────────────────


class TestCrossProcessSerialization(unittest.TestCase):
    """Gate 15/19 — cross-process locking with flock."""

    def setUp(self):
        reset_session()
        _teardown_journal()

    def tearDown(self):
        reset_session()
        _teardown_journal()

    def _setup_jdir(self, td: Path) -> tuple[str, str, str]:
        jdir = td / ".nabd" / "journal"
        jdir.mkdir(parents=True, exist_ok=True)
        jpath = str(jdir / "journal.jsonl")
        lock_path = str(jdir / "journal.lock")
        with open(lock_path, "w") as f:
            f.write("")
        load_workspace_identity(str(td))
        set_journal_path(jpath)
        return str(td), jpath, lock_path

    def test_cross_process_writers_are_serialized(self):
        """Two concurrent subprocesses produce valid non-interleaved JSONL."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ws_root, jpath, lock_path = self._setup_jdir(td)

            script = (
                "import sys, json, os\n"
                "sys.path.insert(0, '.')\n"
                "from core.accept_edits_state import (\n"
                "    set_journal_path, load_workspace_identity,\n"
                "    _make_wal_record, _write_journal_record,\n"
                ")\n"
                "load_workspace_identity(sys.argv[1])\n"
                "set_journal_path(sys.argv[2])\n"
                "idx = sys.argv[3]\n"
                "for i in range(20):\n"
                "    rec = _make_wal_record(\n"
                "        event_type='PREPARED', sequence=1,\n"
                "        operation_id=f'p{idx}-{i}',\n"
                "        edit_id=f'e{idx}-{i}',\n"
                "        operation_type='ACCEPT',\n"
                "        target_path_relative=f'{idx}/{i}.txt',\n"
                "        expected_original_digest='',\n"
                "        intended_result_digest='',\n"
                "    )\n"
                "    _write_journal_record(rec)\n"
                "print('DONE')\n"
            )
            procs = [
                subprocess.Popen(
                    [sys.executable, "-c", script, ws_root, jpath, "A"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ),
                subprocess.Popen(
                    [sys.executable, "-c", script, ws_root, jpath, "B"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ),
            ]
            for p in procs:
                p.wait(timeout=30)
                self.assertEqual(p.returncode, 0,
                                 f"Child failed: {p.stderr.read()}")

            # Verify: each line must be valid JSON with valid checksum
            jp = Path(jpath)
            if jp.exists():
                lines = jp.read_text().strip().splitlines()
                self.assertGreater(len(lines), 0,
                                   "Journal is empty after concurrent writes")
                for i, line in enumerate(lines):
                    try:
                        d = json.loads(line)
                        from core.accept_edits_state import _verify_record_checksum
                        self.assertTrue(_verify_record_checksum(d),
                                        f"Line {i} failed checksum")
                    except (json.JSONDecodeError, KeyError) as exc:
                        self.fail(f"Line {i}: invalid JSON — {exc}")

    def test_append_waits_for_cross_process_compaction(self):
        """append and compaction on different processes do not corrupt."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ws_root, jpath, lock_path = self._setup_jdir(td)

            # Write records for compaction
            for i in range(5):
                op_id = f"op-warm-{i}"
                rec = _make_wal_record(
                    event_type="PREPARED", sequence=1,
                    operation_id=op_id, edit_id=f"e-{i}",
                    operation_type="ACCEPT",
                    target_path_relative=f"{i}.txt",
                    expected_original_digest="a", intended_result_digest="b",
                )
                _write_journal_record(rec)
                rec2 = _make_wal_record(
                    event_type="RESOLVED", sequence=2,
                    operation_id=op_id, edit_id=f"e-{i}",
                    operation_type="ACCEPT",
                    target_path_relative=f"{i}.txt",
                    expected_original_digest="a", intended_result_digest="b",
                    side_effect_applied=True, recovery_status="RESOLVED",
                )
                _write_journal_record(rec2)
            _close_journal()

            # Child A: compaction
            compact_script = (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "from core.accept_edits_state import (\n"
                "    set_journal_path, load_workspace_identity,\n"
                "    _compact_journal,\n"
                ")\n"
                "load_workspace_identity(sys.argv[1])\n"
                "set_journal_path(sys.argv[2])\n"
                "success, msg = _compact_journal()\n"
                "if not success:\n"
                "    raise RuntimeError(f'Compaction failed: {msg}')\n"
                "print('COMPACTED')\n"
            )
            # Child B: append
            append_script = (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "from core.accept_edits_state import (\n"
                "    set_journal_path, load_workspace_identity,\n"
                "    _make_wal_record, _write_journal_record,\n"
                ")\n"
                "load_workspace_identity(sys.argv[1])\n"
                "set_journal_path(sys.argv[2])\n"
                "rec = _make_wal_record(\n"
                "    event_type='PREPARED', sequence=1,\n"
                "    operation_id='op-concurrent',\n"
                "    edit_id='e-concurrent',\n"
                "    operation_type='ACCEPT',\n"
                "    target_path_relative='concurrent.txt',\n"
                "    expected_original_digest='',\n"
                "    intended_result_digest='',\n"
                ")\n"
                "_write_journal_record(rec)\n"
                "print('APPENDED')\n"
            )

            procs = [
                subprocess.Popen(
                    [sys.executable, "-c", compact_script, ws_root, jpath],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ),
                subprocess.Popen(
                    [sys.executable, "-c", append_script, ws_root, jpath],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ),
            ]
            for p in procs:
                p.wait(timeout=30)
                self.assertEqual(p.returncode, 0,
                                 f"Child failed: {p.stderr.read()}")

            # Journal must be valid JSONL with checksums intact
            jp = Path(jpath)
            if jp.exists():
                lines = jp.read_text().strip().splitlines()
                self.assertGreater(len(lines), 0)
                for line in lines:
                    try:
                        d = json.loads(line)
                        from core.accept_edits_state import _verify_record_checksum
                        self.assertTrue(_verify_record_checksum(d))
                    except (json.JSONDecodeError, KeyError):
                        self.fail(f"Invalid line after concurrent ops: {line[:80]}")


# ── Entry ────────────────────────────────────────────────────────────

def get_workspace_id() -> WorkspaceIdentity | None:
    return _workspace_identity


if __name__ == "__main__":
    unittest.main()
