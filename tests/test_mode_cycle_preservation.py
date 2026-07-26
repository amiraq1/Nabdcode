"""Tests proving that mode cycling preserves pending edits.

The old _cycle_mode() called reset_session() on every non-accept-edits mode,
which could wipe pending edits when the user cycled modes.  The fix uses
set_mode() (which toggles the flag without clearing the queue) and reserves
reset_session() for /clear and session landing only.

Required sequence to prove: False → True → False (reset) must preserve
pending edits at every step except the final reset_session().
"""

import unittest

from core.accept_edits_state import (
    PendingEdit,
    reset_session,
    set_mode,
    drain_pending,
    has_pending_edits,
    pending_edit_count,
)


def _make_pending_edit(path: str = "test.py") -> PendingEdit:
    return PendingEdit(
        path=path,
        resolved_path=f"/workspace/{path}",
        old_content="old content",
        new_content="new content",
        diff="-old +new",
        additions=1,
        removals=1,
    )


class TestSetModePreservesPendingEdits(unittest.TestCase):
    """set_mode() must toggle the flag WITHOUT clearing the pending queue."""

    def setUp(self):
        reset_session()

    def test_set_mode_true_preserves_pending_edits(self):
        """Enabling accept-edits mode must not clear existing pending edits."""
        from core.accept_edits_state import _accept_edits_pending
        _accept_edits_pending.append(_make_pending_edit())
        self.assertEqual(pending_edit_count(), 1)

        set_mode(True)
        self.assertEqual(pending_edit_count(), 1)
        self.assertTrue(has_pending_edits())

    def test_set_mode_false_preserves_pending_edits(self):
        """Disabling accept-edits mode must not clear existing pending edits."""
        from core.accept_edits_state import _accept_edits_pending
        _accept_edits_pending.append(_make_pending_edit())
        set_mode(True)
        self.assertTrue(has_pending_edits())

        set_mode(False)
        self.assertEqual(pending_edit_count(), 1)
        # has_pending_edits is False because the flag is off, but the
        # queue itself is preserved — drain_pending() would still return it.
        self.assertFalse(has_pending_edits())
        drained = drain_pending()
        self.assertEqual(len(drained), 1)

    def test_set_mode_does_not_clear_queue(self):
        """set_mode() never clears the pending queue, regardless of direction."""
        from core.accept_edits_state import _accept_edits_pending
        for i in range(3):
            _accept_edits_pending.append(_make_pending_edit(f"file{i}.py"))
        self.assertEqual(pending_edit_count(), 3)

        set_mode(True)
        self.assertEqual(pending_edit_count(), 3)
        set_mode(False)
        self.assertEqual(pending_edit_count(), 3)
        set_mode(True)
        self.assertEqual(pending_edit_count(), 3)


class TestModeCyclePreservesPendingEdits(unittest.TestCase):
    """The full False → True → False → reset cycle must preserve pending edits.

    This is the critical test: cycling modes must NOT wipe the queue.
    Only reset_session() (the final step) clears it.
    """

    def setUp(self):
        reset_session()

    def test_false_to_true_to_false_preserves_pending(self):
        """False → True → False: pending edits survive every mode toggle."""
        import core.accept_edits_state as _state

        # Start: mode off, queue empty
        self.assertFalse(_state._accept_edits_enabled)
        self.assertEqual(pending_edit_count(), 0)

        # Step 1: user enters accept-edits mode (False → True)
        set_mode(True)
        self.assertTrue(_state._accept_edits_enabled)
        self.assertEqual(pending_edit_count(), 0)

        # Agent produces pending edits while in accept-edits mode
        _state._accept_edits_pending.append(_make_pending_edit("a.py"))
        _state._accept_edits_pending.append(_make_pending_edit("b.py"))
        self.assertEqual(pending_edit_count(), 2)
        self.assertTrue(has_pending_edits())

        # Step 2: user cycles back to normal mode (True → False)
        set_mode(False)
        self.assertFalse(_state._accept_edits_enabled)
        # CRITICAL: queue must still have 2 edits, not 0
        self.assertEqual(pending_edit_count(), 2)
        # has_pending_edits is False (flag off) but queue is intact
        self.assertFalse(has_pending_edits())

        # Step 3: user cycles back to accept-edits mode (False → True)
        set_mode(True)
        self.assertTrue(_state._accept_edits_enabled)
        self.assertEqual(pending_edit_count(), 2)
        self.assertTrue(has_pending_edits())

        # Step 4: user cycles back to normal mode (True → False) again
        set_mode(False)
        self.assertFalse(_state._accept_edits_enabled)
        self.assertEqual(pending_edit_count(), 2)

        # Step 5: /clear or session landing → reset_session()
        reset_session()
        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(_state._accept_edits_enabled)
        self.assertFalse(has_pending_edits())

    def test_mode_cycle_preserves_multiple_edits_across_cycles(self):
        """Multiple mode cycles must not lose pending edits."""
        from core.accept_edits_state import _accept_edits_pending

        _accept_edits_pending.append(_make_pending_edit("x.py"))
        initial_count = pending_edit_count()

        for _ in range(5):
            set_mode(True)
            set_mode(False)
            self.assertEqual(pending_edit_count(), initial_count)

        # Only reset_session clears
        reset_session()
        self.assertEqual(pending_edit_count(), 0)


class TestDrainPendingPreservesUntilDrained(unittest.TestCase):
    """drain_pending() must return edits and clear the queue."""

    def setUp(self):
        reset_session()

    def test_drain_returns_and_clears(self):
        from core.accept_edits_state import _accept_edits_pending
        _accept_edits_pending.append(_make_pending_edit("a.py"))
        _accept_edits_pending.append(_make_pending_edit("b.py"))

        drained = drain_pending()
        self.assertEqual(len(drained), 2)
        self.assertEqual(pending_edit_count(), 0)

    def test_drain_after_mode_cycle(self):
        """drain_pending() works correctly after mode cycling."""
        from core.accept_edits_state import _accept_edits_pending
        _accept_edits_pending.append(_make_pending_edit("a.py"))

        set_mode(False)
        set_mode(True)
        set_mode(False)

        drained = drain_pending()
        self.assertEqual(len(drained), 1)
        self.assertEqual(pending_edit_count(), 0)


class TestResetSessionClearsEverything(unittest.TestCase):
    """reset_session() is the nuclear option — clears queue AND flag."""

    def setUp(self):
        reset_session()

    def test_reset_session_clears_queue_and_flag(self):
        from core.accept_edits_state import _accept_edits_pending
        _accept_edits_pending.append(_make_pending_edit())
        set_mode(True)

        reset_session()

        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(has_pending_edits())

    def test_reset_session_on_clear_command(self):
        """Simulate /clear: reset_session() wipes everything."""
        from core.accept_edits_state import _accept_edits_pending
        _accept_edits_pending.append(_make_pending_edit("task1.py"))
        _accept_edits_pending.append(_make_pending_edit("task2.py"))
        set_mode(True)

        # /clear
        reset_session()

        self.assertEqual(pending_edit_count(), 0)
        self.assertFalse(has_pending_edits())
        self.assertFalse(_accept_edits_pending)


if __name__ == "__main__":
    unittest.main()
