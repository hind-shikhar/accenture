"""
Live LLM provider — routes through LiteLLM to a real hosted model
(OpenAI, Anthropic, etc). Only ever selected by ProviderFactory when
DEMO_MODE=false and a matching API key is configured; MockProvider is
used otherwise so the rest of the pipeline never needs to care which
provider is live.
"""
import os
from typing import Any, Dict, AsyncGenerator
from backend.app.providers.base import ModelProvider
import structlog

logger = structlog.get_logger()

try:
    import litellm
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False

# Maps this project's internal routing tiers to real model names.
# Override via env vars to point at whichever provider's key is configured.
MODEL_MAP = {
    "mock-fast": os.getenv("FAST_MODEL", "gpt-4o-mini"),
    "mock-smart": os.getenv("SMART_MODEL", "gpt-4o"),
    "mock-secure": os.getenv("SECURE_MODEL", "gpt-4o-mini"),
    # Deliberately defaults to a different model than mock-smart: the
    # AI-Judge (backend/app/evaluation/ai_judge.py) must not grade the same
    # model's own output when the router picks the smart tier for generation.
    "mock-judge": os.getenv("JUDGE_MODEL", "gpt-4o-mini"),
}


class LiteLLMProvider(ModelProvider):
    """Calls a real hosted model via LiteLLM's unified completion API."""

    async def generate(self, prompt: str, model: str, **kwargs) -> Dict[str, Any]:
        real_model = MODEL_MAP.get(model, model)
        completion_kwargs: Dict[str, Any] = dict(
            model=real_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", 2048),
            temperature=kwargs.get("temperature", 0.2),
            num_retries=0,
            timeout=kwargs.get("timeout", 60),
        )
        # Only passed through when the caller explicitly requests it (e.g.
        # AIJudge asking for JSON-mode output) — not every model LiteLLM
        # routes to accepts response_format, so this is opt-in per call.
        if kwargs.get("response_format"):
            completion_kwargs["response_format"] = kwargs["response_format"]
        response = await litellm.acompletion(**completion_kwargs)
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return {
            "text": text,
            "model": real_model,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            },
        }

    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        real_model = MODEL_MAP.get(model, model)
        response = await litellm.acompletion(
            model=real_model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def health(self) -> bool:
        return LITELLM_AVAILABLE

    async def estimate_cost(self, prompt: str, model: str) -> float:
        real_model = MODEL_MAP.get(model, model)
        try:
            return litellm.completion_cost(
                model=real_model,
                prompt=prompt,
                completion="",
            )
        except Exception:
            return 0.0
