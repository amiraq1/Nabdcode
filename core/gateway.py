# core/gateway.py
"""
High-Fidelity Input Gateway & Model Resolution Subsystem for Nabd OS.

Architectural DNA inspired by elite frontier CLI Input Gateways:
  1. Provider Enum: Mt/Dt gateways (ANTHROPIC, OPENAI, VERCEL_AI_GATEWAY, CLOUDFLARE_AI_GATEWAY, CMD_AI, OPENROUTER).
  2. parseModelString: Colon-split parser mapping raw 'provider:model' strings to structured ResolvedRoute.
  3. migrateDeprecatedModelId: Auto-migrates old/deprecated model IDs (Jt/Yt mapping).
  4. tryResolveCanonical: Canonical model-to-gateway alias resolver.
  5. getModelCategory & getMinimumPlanForModel: Classifies Premium vs Open-Source and gates access by plan tier.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Dict, Final, Set


class ProviderGateway(enum.Enum):
    """Supported AI Provider Gateways (Mt / Dt)."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    BASETEN = "baseten"
    VERCEL_AI_GATEWAY = "vercel-ai-gateway"
    CLOUDFLARE_AI_GATEWAY = "cloudflare-ai-gateway"
    CMD_AI = "cmd-ai"
    OPENROUTER = "openrouter"
    SPIDER_WEB = "spider_web"


class ModelCategory(enum.Enum):
    """Model classification category."""
    PREMIUM = "premium"
    OPENSOURCE = "opensource"


class PlanTier(enum.Enum):
    """User access plan tier."""
    FREE = "free"
    PRO = "pro"
    TEAMS = "teams"


@dataclass(frozen=True)
class ResolvedRoute:
    provider: ProviderGateway
    model_id: str
    canonical_id: str
    category: ModelCategory
    minimum_plan: PlanTier


OPEN_GATEWAYS: Final[Set[ProviderGateway]] = {
    ProviderGateway.VERCEL_AI_GATEWAY,
    ProviderGateway.CMD_AI,
    ProviderGateway.CLOUDFLARE_AI_GATEWAY,
    ProviderGateway.OPENROUTER,
}

DEPRECATED_MODELS: Final[Dict[str, str]] = {
    "claude-sonnet-4-20250514": "claude-sonnet-4-6",
    "gemini-3.0-pro-exp": "gemini-3.5-pro",
    "gpt-4.5-preview": "gpt-5",
}

PREMIUM_MODELS: Final[Set[str]] = {
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "claude-3-5-sonnet",
    "claude-sonnet-4-6",
    "gpt-4o",
    "gpt-5",
    "sakana/fugu-ultra",
    "muse-spark-1.1",
}

# Canonical model aliases across gateways (qt table representation)
GATEWAY_ALIASES: Final[Dict[str, Dict[ProviderGateway, str]]] = {
    "zai-org/GLM-5": {
        ProviderGateway.VERCEL_AI_GATEWAY: "zai/glm-5",
        ProviderGateway.BASETEN: "zai-org/GLM-5",
    },
    "moonshotai/Kimi-K2.5": {
        ProviderGateway.VERCEL_AI_GATEWAY: "moonshot/kimi-k2.5",
        ProviderGateway.OPENROUTER: "moonshotai/kimi-k2.5",
    },
}


class InputGateway:
    """Deterministic Provider/Model Resolution Gateway."""

    @staticmethod
    def migrate_deprecated_model_id(model_id: str) -> str:
        """Migrate deprecated model IDs to modern canonical equivalents."""
        clean = model_id.strip()
        return DEPRECATED_MODELS.get(clean, clean)

    @classmethod
    def try_resolve_canonical(cls, model_id: str, provider: ProviderGateway) -> str:
        """Resolve canonical model ID to gateway-specific alias."""
        migrated = cls.migrate_deprecated_model_id(model_id)
        aliases = GATEWAY_ALIASES.get(migrated)
        if aliases and provider in aliases:
            return aliases[provider]
        return migrated

    @staticmethod
    def get_model_category(provider: ProviderGateway, model_id: str) -> ModelCategory:
        """Classify model as PREMIUM or OPENSOURCE."""
        if model_id in PREMIUM_MODELS:
            return ModelCategory.PREMIUM
        if provider in OPEN_GATEWAYS:
            return ModelCategory.OPENSOURCE
        return ModelCategory.PREMIUM

    @staticmethod
    def get_minimum_plan_for_model(category: ModelCategory) -> PlanTier:
        """Determine minimum required plan tier for the category."""
        if category == ModelCategory.OPENSOURCE:
            return PlanTier.FREE
        return PlanTier.PRO

    @classmethod
    def parse_model_string(cls, raw_input: str, default_provider: ProviderGateway = ProviderGateway.ANTHROPIC) -> ResolvedRoute:
        """
        Parse raw user/model input ('provider:model') and return structured ResolvedRoute.
        Splits at first colon only.
        """
        raw = raw_input.strip() if raw_input else ""
        if ":" in raw:
            parts = raw.split(":", 1)
            provider_str = parts[0].strip().lower()
            model_raw = parts[1].strip()
            try:
                provider = ProviderGateway(provider_str)
            except ValueError:
                provider = default_provider
        else:
            provider = default_provider
            model_raw = raw

        migrated = cls.migrate_deprecated_model_id(model_raw)
        canonical = cls.try_resolve_canonical(migrated, provider)
        category = cls.get_model_category(provider, canonical)
        plan = cls.get_minimum_plan_for_model(category)

        return ResolvedRoute(
            provider=provider,
            model_id=canonical,
            canonical_id=migrated,
            category=category,
            minimum_plan=plan,
        )
