from typing import Dict
import os
from backend.app.providers.base import ModelProvider
from backend.app.providers.mock import MockProvider
import structlog

logger = structlog.get_logger()


class ProviderFactory:
    _providers: Dict[str, ModelProvider] = {}

    @classmethod
    def is_live(cls) -> bool:
        """True only when DEMO_MODE=false AND a real API key is configured."""
        demo_mode = os.getenv("DEMO_MODE", "true").lower() == "true"
        has_key = bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))
        return not demo_mode and has_key

    @classmethod
    def get_provider(cls, provider_name: str) -> ModelProvider:
        if provider_name == "mock" or not cls.is_live():
            return cls._cached("mock", MockProvider)

        try:
            from backend.app.providers.litellm_provider import LiteLLMProvider, LITELLM_AVAILABLE
            if not LITELLM_AVAILABLE:
                raise ImportError("litellm not installed")
            return cls._cached("live", LiteLLMProvider)
        except Exception as e:
            logger.warning("live_provider_unavailable_falling_back_to_mock", error=str(e))
            return cls._cached("mock", MockProvider)

    @classmethod
    def _cached(cls, key: str, provider_cls) -> ModelProvider:
        if key not in cls._providers:
            cls._providers[key] = provider_cls()
        return cls._providers[key]
