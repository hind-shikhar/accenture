"""
Cost model for the governance layer.

Two cost centers exist on every request:
  1. The underlying LLM call (token-based, varies by routed model).
  2. The governance/detection compute itself (PII scan, hallucination check,
     bias classifier, retrieval verify, AI-judge, injection scan) — the
     "governance tax" enterprises pay on top of the raw model call.

These are illustrative unit-economics numbers (documented, not hidden),
meant to make the cost/latency tradeoff visible and tunable rather than
to be a production billing source of truth. Swap in real provider invoices
or a token-metering sidecar to replace this in production.
"""
from typing import Dict, Optional

# $ per 1,000 tokens (prompt+completion blended), by routed model id.
MODEL_COST_PER_1K_TOKENS: Dict[str, float] = {
    "mock-fast": 0.0003,
    "mock-smart": 0.0060,
    "mock-secure": 0.0015,
}
DEFAULT_MODEL_COST_PER_1K = 0.0015

# Flat $ per call for each detector, reflecting relative CPU cost of the
# underlying method. ML inference paths cost meaningfully more than
# regex/heuristic paths — this is what "skip the expensive detector on the
# realtime tier" is actually buying back.
DETECTOR_COST_USD: Dict[str, float] = {
    "security_scan_ml": 0.00035,  # Presidio NER + DeBERTa-v3 injection classifier (CPU)
    "security_scan": 0.00010,     # Presidio + spaCy NER, regex injection scan only
    "response_pii": 0.00010,      # Presidio + spaCy NER
    "hallucination": 0.00015,     # DistilBERT sentiment inference (CPU)
    "bias_ml": 0.00090,           # BART-large-mnli zero-shot (CPU, ~400M params)
    "bias_heuristic": 0.00001,    # keyword pattern match, effectively free
    "retrieval": 0.00004,         # local doc-store cross-reference
    "ai_judge": 0.00003,          # heuristic claim/consistency scoring
    "injection_ml": 0.00025,      # DeBERTa-v3 injection classifier (CPU)
    "injection": 0.000005,        # regex scan
}


def estimate_llm_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    rate = MODEL_COST_PER_1K_TOKENS.get(model_id, DEFAULT_MODEL_COST_PER_1K)
    total_tokens = max(prompt_tokens + completion_tokens, 0)
    return round((total_tokens / 1000.0) * rate, 6)


def estimate_detector_cost(detector: str, ml_used: Optional[bool] = None) -> float:
    if detector == "bias":
        return DETECTOR_COST_USD["bias_ml"] if ml_used else DETECTOR_COST_USD["bias_heuristic"]
    if detector in ("security_scan", "injection") and ml_used:
        return DETECTOR_COST_USD[f"{detector}_ml"]
    return DETECTOR_COST_USD.get(detector, 0.0)
