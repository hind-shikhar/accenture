from typing import Dict, Any
from backend.app.schemas.chat import ChatRequest, RouteResult

class SemanticRouter:
    def __init__(self):
        # In a real app, these would come from a DB or config
        self.models = [
            {"id": "mock-fast", "provider": "mock", "cost": 0.0001, "latency": 100, "capability": 5},
            {"id": "mock-smart", "provider": "mock", "cost": 0.01, "latency": 800, "capability": 9},
            {"id": "mock-secure", "provider": "mock", "cost": 0.005, "latency": 400, "capability": 7},
        ]

    async def route(self, request: ChatRequest) -> RouteResult:
        """Route the request to the best model based on budget and requirements."""
        
        # Simple heuristic router for MVP
        selected = self.models[0]
        reason = "Default fallback"
        
        if request.sensitivity == "high":
            selected = next((m for m in self.models if m["id"] == "mock-secure"), self.models[0])
            reason = "Selected secure model due to high sensitivity"
        elif request.task_type == "complex" or (request.cost_budget and request.cost_budget > 0.005):
            selected = next((m for m in self.models if m["id"] == "mock-smart"), self.models[0])
            reason = "Selected smart model for complex task"
        else:
            selected = next((m for m in self.models if m["id"] == "mock-fast"), self.models[0])
            reason = "Selected fast model for general task"
            
        return RouteResult(
            selected_model=selected["id"],
            provider=selected["provider"],
            reason=reason,
            estimated_cost=selected["cost"],
            estimated_latency=selected["latency"]
        )
