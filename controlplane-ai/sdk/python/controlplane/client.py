import httpx
from typing import Dict, Any, Optional

class ControlPlaneClient:
    """SDK for interacting with ControlPlane.ai Gateway."""
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {}
        )

    async def chat(
        self,
        prompt: str,
        task_type: str = "general",
        sensitivity: str = "low",
        policy: str = "enterprise_default"
    ) -> Dict[str, Any]:
        """
        Send a request through the ControlPlane middleware.
        """
        payload = {
            "prompt": prompt,
            "task_type": task_type,
            "sensitivity": sensitivity,
            "policy": policy
        }
        
        response = await self.client.post("/api/v1/chat", json=payload, timeout=30.0)
        response.raise_for_status()
        return response.json()
        
    async def close(self):
        await self.client.aclose()
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
