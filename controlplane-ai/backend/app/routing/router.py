from typing import Dict, Any, Optional
from backend.app.schemas.chat import ChatRequest, RouteResult
from backend.app.providers.factory import ProviderFactory

# Exponential-moving-average smoothing for observed per-model cost/latency —
# weights recent requests more heavily so the estimate adapts as traffic
# patterns shift, without needing to store/replay full request history.
_EMA_ALPHA = 0.2
# Don't trust the observed average over the static fallback until there's
# enough real traffic for it to mean something — avoids one unusually
# slow/expensive first request permanently skewing the estimate.
_MIN_SAMPLES_BEFORE_TRUSTING_OBSERVED = 5


class SemanticRouter:
    def __init__(self):
        # Static fallback catalog — used until enough real traffic has been
        # observed to replace cost/latency with live measurements (see
        # record_observed_stats/_estimate_for below). "capability" has no
        # traffic signal to derive it from (that needs a quality/eval score,
        # not just cost/latency), so it stays a fixed editorial judgment;
        # "id" also stays fixed — it's what ProviderFactory/LiteLLMProvider's
        # MODEL_MAP key off of, not a number to calibrate.
        self.models = [
            {"id": "mock-fast", "cost": 0.0001, "latency": 100, "capability": 5},
            {"id": "mock-smart", "cost": 0.01, "latency": 800, "capability": 9},
            {"id": "mock-secure", "cost": 0.005, "latency": 400, "capability": 7},
        ]
        # model_id -> {"cost": ema, "latency": ema, "samples": n}
        self._observed: Dict[str, Dict[str, float]] = {}

    def record_observed_stats(self, model_id: str, cost_usd: Optional[float], latency_ms: Optional[float]):
        """Feed a real request's actual LLM cost/latency back into this
        model tier's running estimate. backend/app/workflows/graph.py's
        node_llm already tracks these per-request as
        detector_costs['llm']/detector_latencies['llm'] — api/chat.py calls
        this after every request so route()'s estimated_cost/estimated_latency
        reflect what's actually happening in production instead of a static
        guess made before this model tier had ever been called."""
        if cost_usd is None and latency_ms is None:
            return
        stats = self._observed.setdefault(model_id, {"cost": 0.0, "latency": 0.0, "samples": 0})
        if stats["samples"] == 0:
            stats["cost"] = cost_usd if cost_usd is not None else 0.0
            stats["latency"] = latency_ms if latency_ms is not None else 0.0
        else:
            if cost_usd is not None:
                stats["cost"] = _EMA_ALPHA * cost_usd + (1 - _EMA_ALPHA) * stats["cost"]
            if latency_ms is not None:
                stats["latency"] = _EMA_ALPHA * latency_ms + (1 - _EMA_ALPHA) * stats["latency"]
        stats["samples"] += 1

    def _estimate_for(self, model: Dict[str, Any]) -> Dict[str, float]:
        observed = self._observed.get(model["id"])
        if observed and observed["samples"] >= _MIN_SAMPLES_BEFORE_TRUSTING_OBSERVED:
            return {"cost": observed["cost"], "latency": observed["latency"]}
        return {"cost": model["cost"], "latency": model["latency"]}

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

        provider = "live" if ProviderFactory.is_live() else "mock"
        estimate = self._estimate_for(selected)

        return RouteResult(
            selected_model=selected["id"],
            provider=provider,
            reason=reason,
            estimated_cost=round(estimate["cost"], 6),
            estimated_latency=round(estimate["latency"], 1),
        )
