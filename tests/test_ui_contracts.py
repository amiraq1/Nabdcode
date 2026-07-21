"""Contract tests for Bento UI Phase 1 requirements (Reject-Only Busy Policy, Bridge, Sanitization)."""

from __future__ import annotations

import unittest
from unittest import mock
from core.ui_bridge import UIBridge, UIBridgeProtocol, get_bridge, set_bridge
from core.sanitize import sanitize
from ui.controllers.agent_controller import AgentUiController
from ui.widgets.prompt import Prompt, ActivePromptInput
from ui.widgets.spinner import Spinner
from ui.widgets.badges import ActionTag, AgentThought


class TestUiContracts(unittest.TestCase):
    """Verify Phase 1 UI contracts: Busy rejection policy, Bridge contracts, and Stateless widgets."""

    def test_second_prompt_rejected_while_busy(self) -> None:
        """Verify: Second prompt -> Rejected -> while busy == True."""
        controller = AgentUiController()
        
        # When idle (busy == False), submitting a prompt succeeds.
        self.assertFalse(controller.is_busy)
        self.assertTrue(controller.try_submit_prompt("First prompt (or goal prompt)"))

        # Simulate controller becoming busy during execution.
        controller.is_busy = True

        # When busy == True, submitting a second prompt is immediately rejected.
        self.assertFalse(
            controller.try_submit_prompt("Second prompt"),
            "Second prompt must be rejected immediately while busy == True under Phase 1 Reject-Only policy.",
        )
        self.assertFalse(
            controller.try_submit_prompt("Analyze codebase"),
            "Any standard prompt must return False immediately while busy.",
        )

        # Only /help and /clear remain available while busy.
        self.assertTrue(
            controller.try_submit_prompt("/help"),
            "/help must remain available even when busy.",
        )
        self.assertTrue(
            controller.try_submit_prompt("/clear"),
            "/clear must remain available even when busy.",
        )

    def test_bridge_protocol_and_registration(self) -> None:
        """Verify process-wide registration get_bridge()/set_bridge() and typing.Protocol adherence."""
        bridge = get_bridge()
        self.assertIsNotNone(bridge, "Core code must never perform None checks on get_bridge().")
        self.assertIsInstance(bridge, UIBridgeProtocol, "Bridge must satisfy UIBridgeProtocol contract.")

        controller = AgentUiController()
        self.assertIsInstance(controller, UIBridgeProtocol)
        
        set_bridge(controller)
        self.assertIs(get_bridge(), controller)

        # Resetting with None must revert to the no-op default without allowing None.
        set_bridge(None)
        self.assertIsNotNone(get_bridge())
        self.assertIsInstance(get_bridge(), UIBridgeProtocol)

    def test_stateless_widgets_and_sanitization(self) -> None:
        """Verify stateless widgets are presentation only and sanitization strips ANSI codes."""
        raw_text = "\x1b[31mDangerous <script>alert(1)</script> ANSI\x1b[0m"
        clean_text = sanitize(raw_text)
        self.assertNotIn("\x1b[", clean_text, "sanitize() must strip ANSI sequences before UI mount.")

        prompt = Prompt(clean_text)
        self.assertEqual(prompt.prompt_text, clean_text)

        spinner = Spinner("Loading...")
        self.assertEqual(spinner.spinner_text, "Loading...")


if __name__ == "__main__":
    unittest.main()
