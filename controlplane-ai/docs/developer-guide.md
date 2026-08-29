# Developer Guide

## SDK Usage

```python
import asyncio
from sdk.python.controlplane.client import ControlPlaneClient

async def main():
    async with ControlPlaneClient() as client:
        result = await client.chat("Hello AI", sensitivity="low")
        print(result["text"])
        print(result["trust_score"])

asyncio.run(main())
```

## Adding new Providers
To add a new provider, inherit from `ModelProvider` in `backend/app/providers/base.py` and register it in `backend/app/providers/factory.py`.
