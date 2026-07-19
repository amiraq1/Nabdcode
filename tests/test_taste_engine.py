"""tests/test_taste_engine.py — Unit verification suite for TasteEngine and TasteProfile."""

import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from core.taste_engine import TasteProfile, TasteEngine


class TestTasteEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.engine = TasteEngine(workspace_dir=self.test_dir)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_default_profile_creation_and_caching(self):
        # 1. Profile should not exist yet on disk before load
        self.assertFalse(os.path.exists(self.engine.profile_path))

        # 2. Loading should initialize default profile and write to disk
        profile = self.engine.load_profile()
        self.assertTrue(os.path.exists(self.engine.profile_path))
        self.assertIn("Prefer zero-dependency solutions when possible.", profile.architectural_rules)
        self.assertIn("Interact with the user in Arabic.", profile.language_preferences)

        # 3. Subsequent load should return the identical cached object in memory
        profile2 = self.engine.load_profile()
        self.assertIs(profile, profile2)

    def test_save_profile_and_summary_generation(self):
        profile = self.engine.load_profile()
        profile.custom_rules.append("Always use lazy imports in __init__.py.")
        self.engine.save_profile(profile)

        # Verify disk persistence across new instance
        engine2 = TasteEngine(workspace_dir=self.test_dir)
        loaded = engine2.load_profile()
        self.assertIn("Always use lazy imports in __init__.py.", loaded.custom_rules)

        # Verify prompt summary formatting
        summary = engine2.get_taste_summary_for_prompt()
        self.assertIn("## Developer Taste Profile (Mandatory Rules)", summary)
        self.assertIn("### Architectural Rules:", summary)
        self.assertIn("- Always use lazy imports in __init__.py.", summary)


if __name__ == "__main__":
    unittest.main()
