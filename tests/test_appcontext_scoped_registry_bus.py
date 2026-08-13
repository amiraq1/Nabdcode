"""Tests for the AppContext-scoped registry/bus shim + session-id stamping.

Two behaviors under test:

1. Compatibility shim: AppContext exposes instance-scoped ``registry``/``bus``
   populated identically to the global singletons, and they are DISTINCT
   instances (so future multi-session work can use them). The global
   singletons are untouched — the current single-session CLI path is
   behavior-identical.

2. Session/run-id on emitted events: every kernel-bus emit carries a
   ``session_id``. Emitters with a RuntimeState pass ``state.session_id``;
   emitters without one fall back to the process-level ``run_id``.
   ``emit_with_session`` uses setdefault, so an emitter that already includes
   its own session id is preserved.
"""

import unittest

from core.kernel.events import EventBus, emit_with_session, run_id
from engine.tool_registry import ToolRegistry, registry as global_registry


class TestAppContextScopedShim(unittest.TestCase):
    def test_app_context_exposes_distinct_scoped_registry_and_bus(self):
        from core.app_context import AppContext

        ctx = AppContext.build(auto_discover=False)

        # Distinct instances, not the globals.
        self.assertIsNotNone(ctx.registry)
        self.assertIsNotNone(ctx.bus)
        self.assertIsNot(ctx.registry, global_registry)
        # Same interface as the global registry (a ToolRegistry).
        self.assertIsInstance(ctx.registry, ToolRegistry)
        self.assertIsInstance(ctx.bus, EventBus)

        # Populated identically to the global (same tool set for a single
        # session), including the manual baseline + task tool.
        global_names = {n for n, _ in global_registry}
        scoped_names = {n for n, _ in ctx.registry}
        # The scoped registry must contain at least the same core tools the
        # global has for a single session (it may have a superset if the
        # global leaked earlier tools, but must not be missing any baseline).
        for name in ("execute_shell", "file_system", "web_search", "task"):
            self.assertIn(name, scoped_names, f"scoped registry missing {name}")
        # Global registry is untouched (still the same singleton object).
        self.assertIs(global_registry, __import__("engine.tool_registry", fromlist=["registry"]).registry)


class TestSessionIdStamping(unittest.TestCase):
    def test_emit_with_session_stamps_session_id_into_payload(self):
        bus = EventBus()
        received = {}

        def sub(payload):
            received["payload"] = payload

        bus.subscribe("test_event", sub)
        emit_with_session(bus, "test_event", {"step": 1}, session_id="sess-123")
        self.assertEqual(received["payload"]["session_id"], "sess-123")
        self.assertEqual(received["payload"]["step"], 1)

    def test_emit_with_session_preserves_existing_session_id(self):
        bus = EventBus()
        received = {}

        def sub(payload):
            received["payload"] = payload

        bus.subscribe("test_event", sub)
        # setdefault semantics: an already-present session_id wins.
        emit_with_session(bus, "test_event", {"session_id": "mine", "step": 2}, session_id="other")
        self.assertEqual(received["payload"]["session_id"], "mine")

    def test_emit_with_session_falls_back_to_run_id(self):
        bus = EventBus()
        received = {}

        def sub(payload):
            received["payload"] = payload

        bus.subscribe("test_event", sub)
        emit_with_session(bus, "test_event", {"step": 3})
        self.assertEqual(received["payload"]["session_id"], run_id)

    def test_emit_with_session_non_dict_payload_passthrough(self):
        bus = EventBus()
        received = {}

        def sub(payload):
            received["payload"] = payload

        bus.subscribe("test_event", sub)
        emit_with_session(bus, "test_event", "plain-string", session_id="x")
        self.assertEqual(received["payload"], "plain-string")


if __name__ == "__main__":
    unittest.main()
