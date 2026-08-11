"""tests/test_circuit_breaker_recovery.py — ARCH-3: Circuit Breaker recovery.

Verifies that ``CircuitBreaker``:
  • snapshots state to a SQLite checkpoint when max depth is reached
  • restores state via ``rollback()``
  • emits a ``circuit_opened`` event
  • can ``resume()`` after the circuit opens

Semantics: ``enter()`` increments depth and opens the circuit (returning
False) when ``current_depth >= max_depth``.  Once open, further
``enter()`` calls are blocked until ``resume()``.
"""

from __future__ import annotations

from core.kernel.events import bus
from core.agent_manager import CircuitBreaker


class TestCircuitBreaker:
    def test_depth_guard_allows_progress(self):
        """Normal depth usage stays below max and does not open the circuit."""
        cb = CircuitBreaker(max_depth=3)
        assert cb.enter() is True
        assert cb.enter() is True
        cb.exit()
        assert cb.is_open is False

    def test_state_saved_on_max_depth(self):
        """Reaching max depth opens the circuit and persists a checkpoint."""
        cb = CircuitBreaker(max_depth=2)
        # Snapshot some state before the circuit opens
        cb.checkpoint({"step": 1, "context": "hello"})
        assert cb.enter() is True          # depth 1 < max
        assert cb.enter() is False         # depth 2 >= max → open
        assert cb.is_open is True

    def test_rollback_restores_state(self):
        """``rollback()`` returns the most-recent checkpoint state."""
        cb = CircuitBreaker()
        cb.checkpoint({"step": 1, "data": "first"})
        cb.checkpoint({"step": 2, "data": "second"})
        restored = cb.rollback()
        assert restored is not None
        assert restored["step"] == 2
        assert restored["data"] == "second"

    def test_rollback_empty_returns_none(self):
        """``rollback()`` with no checkpoints returns None."""
        cb = CircuitBreaker()
        assert cb.rollback() is None

    def test_event_emitted_on_circuit_open(self):
        """Opening the circuit emits ``circuit_opened`` on the kernel bus."""
        events = []
        bus.subscribe("circuit_opened", lambda p: events.append(p))
        cb = CircuitBreaker(max_depth=1)
        cb.enter()      # depth hits max → opens circuit (emits once)
        cb.enter()      # already open → blocked, no re-emit
        assert len(events) == 1
        assert events[0]["reason"] == "max_depth_reached"

    def test_resume_clears_open(self):
        """``resume()`` clears the open state so execution may continue."""
        cb = CircuitBreaker(max_depth=2)
        cb.enter()
        assert cb.enter() is False         # depth 2 >= max → open
        assert cb.is_open is True
        cb.resume()
        assert cb.is_open is False
        assert cb.current_depth == 0
        assert cb.enter() is True          # can proceed again

    def test_enter_blocked_when_open(self):
        """Once open, further ``enter()`` calls return False."""
        cb = CircuitBreaker(max_depth=1)
        cb.open_circuit(reason="test")
        assert cb.enter() is False

    def test_checkpoint_persists_across_instances(self, tmp_path):
        """Checkpoints written to a file-backed DB survive instance recreation."""
        db_path = tmp_path / "cb.db"
        cb1 = CircuitBreaker(db_path=db_path)
        cb1.checkpoint({"step": 42})
        cb1._conn.close()

        cb2 = CircuitBreaker(db_path=db_path)
        restored = cb2.rollback()
        assert restored is not None
        assert restored["step"] == 42
        cb2._conn.close()
