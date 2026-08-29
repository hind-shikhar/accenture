import pytest
from backend.app.schemas.chat import ChatRequest
from backend.app.routing.router import SemanticRouter

@pytest.mark.asyncio
async def test_semantic_router_fast():
    router = SemanticRouter()
    req = ChatRequest(prompt="Hello", sensitivity="low", cost_budget=0.001)
    res = await router.route(req)
    assert res.selected_model == "mock-fast"

@pytest.mark.asyncio
async def test_semantic_router_secure():
    router = SemanticRouter()
    req = ChatRequest(prompt="Sensitive data here", sensitivity="high")
    res = await router.route(req)
    assert res.selected_model == "mock-secure"
