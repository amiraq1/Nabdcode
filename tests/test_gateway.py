# tests/test_gateway.py
import unittest
from core.gateway import (
    InputGateway,
    ProviderGateway,
    ModelCategory,
    PlanTier,
)


class TestInputGateway(unittest.TestCase):
    def test_parse_model_string_with_colon_and_alias(self):
        route = InputGateway.parse_model_string("vercel-ai-gateway:zai-org/GLM-5")
        self.assertEqual(route.provider, ProviderGateway.VERCEL_AI_GATEWAY)
        self.assertEqual(route.model_id, "zai/glm-5")
        self.assertEqual(route.category, ModelCategory.OPENSOURCE)
        self.assertEqual(route.minimum_plan, PlanTier.FREE)

    def test_deprecated_model_migration_and_default_provider(self):
        route = InputGateway.parse_model_string("claude-sonnet-4-20250514")
        self.assertEqual(route.provider, ProviderGateway.ANTHROPIC)
        self.assertEqual(route.model_id, "claude-sonnet-4-6")
        self.assertEqual(route.category, ModelCategory.PREMIUM)
        self.assertEqual(route.minimum_plan, PlanTier.PRO)

    def test_unknown_provider_fallback(self):
        route = InputGateway.parse_model_string("unknown_provider:gpt-4o")
        self.assertEqual(route.provider, ProviderGateway.ANTHROPIC)
        self.assertEqual(route.model_id, "gpt-4o")


if __name__ == "__main__":
    unittest.main()
