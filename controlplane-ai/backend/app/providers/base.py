from abc import ABC, abstractmethod
from typing import Any, Dict, AsyncGenerator

class ModelProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, model: str, **kwargs) -> Dict[str, Any]:
        """Generate a complete response."""
        pass

    @abstractmethod
    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream the response."""
        pass

    @abstractmethod
    async def health(self) -> bool:
        """Check provider health."""
        pass

    @abstractmethod
    async def estimate_cost(self, prompt: str, model: str) -> float:
        """Estimate the token cost of the request."""
        pass
