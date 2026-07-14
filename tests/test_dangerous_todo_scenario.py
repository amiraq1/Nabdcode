"""Automated test verifying behavior under the dangerous scenario (failing verification step)."""

import unittest
from core.todo import TodoManager, TodoStatus
from tools.todo import TodoWriteTool


class TestDangerousTodoScenario(unittest.TestCase):
    def test_failing_verification_blocked_from_marking_done_without_evidence(self):
        manager = TodoManager()
        tool = TodoWriteTool(manager)

        # Step 1: Agent creates plan
        tool.execute(
            action="plan",
            items=["Step 1: Write code", "Step 2: Verify syntax via py_compile"],
        )

        # Step 2: Agent marks step 2 in_progress
        tool.execute(action="update", item_id=2, status="in_progress")
        self.assertEqual(manager.all()[1].status, TodoStatus.IN_PROGRESS)

        # Step 3: Agent runs py_compile and encounters a syntax error!
        # If agent attempts to cheat and mark done without valid verification note:
        cheat_result = tool.execute(action="update", item_id=2, status="done", verification_note="")
        self.assertFalse(cheat_result.success)
        self.assertIn("Cannot mark TODO #2 done without a verification_note", cheat_result.stderr)
        # Verify item #2 remains IN_PROGRESS
        self.assertEqual(manager.all()[1].status, TodoStatus.IN_PROGRESS)

        # Step 4: Agent follows discipline rule #5: keeps step IN_PROGRESS and reports failure
        # Item remains IN_PROGRESS until fix is verified
        self.assertEqual(manager.all()[1].status, TodoStatus.IN_PROGRESS)


if __name__ == "__main__":
    unittest.main()
