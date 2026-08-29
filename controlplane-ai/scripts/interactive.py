import asyncio
import sys
import os
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from sdk.python.controlplane.client import ControlPlaneClient

async def interactive_chat():
    print("=====================================================")
    print("[ControlPlane.ai] Interactive Tester")
    print("Type your prompt below to test the governance pipeline.")
    print("Type 'exit' to quit.")
    print("=====================================================")
    
    async with ControlPlaneClient() as client:
        while True:
            prompt = input("\n> You: ")
            if prompt.strip().lower() in ['exit', 'quit']:
                break
                
            try:
                # We send sensitivity="high" if we want to trigger mock-secure, etc.
                res = await client.chat(prompt, sensitivity="high")
                
                print("\n[ControlPlane Allowed Request]")
                print(f"Model Routed To: {res.get('model', 'Unknown')}")
                
                security = res.get('security', {})
                if security.get('pii_detected'):
                    print(f"PII Masked: Yes {security.get('pii_types')}")
                    
                print(f"Trust Score: {res.get('trust_score')}/100")
                print(f"\nResponse: {res.get('text')}")
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    detail = e.response.json().get("detail", {})
                    print("\n[ControlPlane BLOCKED Request]")
                    print(f"Decision: BLOCK")
                    print(f"Reasons: {detail.get('reasons', ['Policy enforced'])}")
                else:
                    print(f"\n[Error] -> {e}")
            except Exception as e:
                print(f"\n[Error] -> {e}")

if __name__ == "__main__":
    asyncio.run(interactive_chat())
