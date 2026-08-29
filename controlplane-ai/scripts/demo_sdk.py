import asyncio
import httpx
import json

# Simulated Enterprise SDK Client
class ControlPlaneClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    async def chat(self, prompt: str, use_case: str = "internal_copilot", geography: str = "global") -> dict:
        async with httpx.AsyncClient() as client:
            payload = {
                "prompt": prompt,
                "use_case": use_case,
                "geography": geography
            }
            try:
                response = await client.post(f"{self.base_url}/api/v1/chat", json=payload, timeout=30.0)
                if response.status_code == 403:
                    return {"decision": "BLOCK", "error": response.json().get("detail", {}).get("message", "Blocked by policy")}
                response.raise_for_status()
                return response.json()
            except Exception as e:
                return {"error": str(e)}

async def main():
    print("🚀 Initializing ControlPlane.ai Python SDK...\n")
    client = ControlPlaneClient()

    print("--------------------------------------------------")
    print("Scenario 1: Standard Enterprise Query")
    print("--------------------------------------------------")
    prompt = "What is the company policy on remote work?"
    print(f"User: {prompt}")
    
    result = await client.chat(prompt, use_case="internal_copilot")
    
    print(f"\n[Decision]: {result.get('decision')}")
    print(f"[Trust Score]: {result.get('trust_score')}/100")
    print(f"[Response]: {result.get('text')}\n")

    print("--------------------------------------------------")
    print("Scenario 2: PII Leakage (Masked Automatically)")
    print("--------------------------------------------------")
    prompt_pii = "Update the contact email to john.doe@acmecorp.com"
    print(f"User: {prompt_pii}")
    
    result_pii = await client.chat(prompt_pii, use_case="customer_support")
    
    print(f"\n[Decision]: {result_pii.get('decision')}")
    print(f"[PII Masked]: {result_pii.get('security', {}).get('pii_detected')}")
    print(f"[Response]: {result_pii.get('text')}\n")

if __name__ == "__main__":
    asyncio.run(main())
