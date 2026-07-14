# tests/test_model_registry.py
import unittest
from core.model_registry import (
    ModelEntry,
    MODEL_REGISTRY,
    is_free_model,
    format_model_selector_label,
    get_model_short_name,
    get_visible_models,
)


class TestModelRegistryAndBadges(unittest.TestCase):
    def test_badge_and_hidden_decoupling(self):
        minimax = MODEL_REGISTRY["MiniMaxAI/MiniMax-M3-Free"]
        tencent = MODEL_REGISTRY["tencent/Hy3"]

        self.assertTrue(is_free_model(minimax))
        self.assertTrue(minimax.hidden)

        self.assertTrue(is_free_model(tencent))
        self.assertFalse(tencent.hidden)

    def test_visible_models_filter(self):
        visible = get_visible_models()
        visible_ids = [m.id for m in visible]
        self.assertIn("tencent/Hy3", visible_ids)
        self.assertNotIn("MiniMaxAI/MiniMax-M3-Free", visible_ids)

    def test_format_model_selector_label(self):
        entry = ModelEntry(id="test/model", name="Test Model", badge="free")
        label = format_model_selector_label(entry, default_id="test/model", col_width=24)
        self.assertIn("Test Model (FREE)", label)
        self.assertIn("(default)", label)

    def test_get_model_short_name(self):
        entry = ModelEntry(id="test/model", name="Test Model", badge="free")
        self.assertEqual(get_model_short_name(entry), "Test Model (free)")


if __name__ == "__main__":
    unittest.main()
