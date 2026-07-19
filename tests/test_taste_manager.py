"""tests/test_taste_manager.py — Unit verification suite for TasteManagerTool."""

import os
import shutil
import tempfile
import unittest
from core.taste_engine import TasteEngine
from tools.taste_manager import TasteManagerTool


class TestTasteManagerTool(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.taste_engine = TasteEngine(workspace_dir=self.test_dir)
        self.tool = TasteManagerTool(taste_engine=self.taste_engine)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_view_action(self):
        out = self.tool.forward(action="view")
        self.assertIn("## Developer Taste Profile (Mandatory Rules)", out)
        self.assertIn("Prefer zero-dependency solutions when possible.", out)

    def test_add_and_remove_rule_actions(self):
        # 1. Add rule
        add_res = self.tool.forward(
            action="add_rule",
            category="architectural_rules",
            rule="Avoid circular dependencies across core modules.",
        )
        self.assertIn("Success: The rule 'Avoid circular dependencies across core modules.' has been permanently added", add_res)

        # Verify through view
        view_res = self.tool.forward(action="view")
        self.assertIn("Avoid circular dependencies across core modules.", view_res)

        # 2. Duplicate add should return notice
        dup_res = self.tool.forward(
            action="add_rule",
            category="architectural_rules",
            rule="Avoid circular dependencies across core modules.",
        )
        self.assertIn("Notice: This rule already exists", dup_res)

        # 3. Remove rule
        rem_res = self.tool.forward(
            action="remove_rule",
            category="architectural_rules",
            rule="Avoid circular dependencies across core modules.",
        )
        self.assertIn("Success: The rule 'Avoid circular dependencies across core modules.' has been removed", rem_res)

        # Verify removal
        view_after = self.tool.forward(action="view")
        self.assertNotIn("Avoid circular dependencies across core modules.", view_after)

    def test_invalid_actions_and_categories(self):
        # Invalid action
        inv_action = self.tool.forward(action="explode")
        self.assertIn("Error: Invalid action.", inv_action)

        # Invalid category
        inv_cat = self.tool.forward(action="add_rule", category="magic_rules", rule="do something")
        self.assertIn("Error: Invalid category 'magic_rules'", inv_cat)

        # Missing rule text
        missing_rule = self.tool.forward(action="add_rule", category="custom_rules")
        self.assertIn("Error: You must provide a 'rule' text", missing_rule)

    def test_execute_returns_tool_result(self):
        res = self.tool.execute(action="add_rule", category="custom_rules", rule="Verify with pytest.")
        self.assertTrue(res.success)
        self.assertIn("Success", res.stdout)
        self.assertEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
