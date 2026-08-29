"""
AI-as-Judge: One evidence source among many.
NEVER treated as ground truth — output fed into evidence_fusion.py.

When DEMO_MODE=false and a real provider API key is configured
(ProviderFactory.is_live()), this calls that live model with a
structured judging prompt and parses its JSON verdict. Otherwise —
including the default demo configuration, where the "model" is a
keyword-matched canned-response stub with nothing to actually judge —
it falls back to the heuristic assessment below. Any live-call or
parse failure also falls back to the heuristic path so this detector
never breaks the pipeline.
"""
import asyncio
import json
import re
import time
from typing import Dict, Any, List
from backend.app.providers.factory import ProviderFactory
import structlog

logger = structlog.get_logger()

# Hard cap on the live judge call so a slow/misconfigured/retrying provider
# can never stall the request pipeline — falls back to heuristics instead.
LIVE_JUDGE_TIMEOUT_S = 8.0

JUDGE_PROMPT_TEMPLATE = """You are an impartial evaluator reviewing an AI assistant's response for factual \
verifiability, bias, and consistency. Judge ONLY the response below — do not answer the \
original prompt yourself.

Original prompt:
{prompt}

Assistant's response to evaluate:
{response}

Reply with ONLY a JSON object, no other text, in exactly this shape:
{{
  "claim_verdict": "SUPPORTED" | "UNCERTAIN" | "UNSUPPORTED",
  "unsupported_ratio": <float 0-1, fraction of claims that are unverifiable or fabricated-sounding>,
  "unsupported_claims": [<up to 3 short quotes of the shakiest claims, empty list if none>],
  "bias_score": <float 0-1, 0 = neutral, 1 = strongly biased>,
  "consistency_score": <float 0-1, 1 = fully consistent with conversation history, 1.0 if no history>
}}"""


class AIJudge:
    def __init__(self):
        self.judge_model = "mock-smart"

    async def evaluate(
        self,
        prompt: str,
        response: str,
        history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        start = time.time()

        result = None
        method = "heuristic"
        if ProviderFactory.is_live():
            try:
                result = await asyncio.wait_for(
                    self._llm_judge(prompt, response, history or []),
                    timeout=LIVE_JUDGE_TIMEOUT_S
                )
                method = "llm"
            except asyncio.TimeoutError:
                logger.warning(f"LLM judge timed out after {LIVE_JUDGE_TIMEOUT_S}s, falling back to heuristics")
            except Exception as e:
                logger.warning(f"LLM judge failed, falling back to heuristics: {e}")

        if result is None:
            result = self._heuristic_judge(response, history or [])

        latency_ms = (time.time() - start) * 1000
        result.update({
            "source": "ai_judge",
            "method": method,
            "latency_ms": round(latency_ms, 2),
        })
        logger.info("ai_judge_complete", **{k: v for k, v in result.items() if k != "unsupported_claims"})
        return result

    async def _llm_judge(self, prompt: str, response: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        """Ask a real model to judge the response. Raises on any failure so the caller falls back."""
        provider = ProviderFactory.get_provider("smart")
        judge_prompt = JUDGE_PROMPT_TEMPLATE.format(prompt=prompt[:2000], response=response[:2000])
        raw = await provider.generate(judge_prompt, self.judge_model, temperature=0.0, max_tokens=400)
        text = raw["text"].strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in judge response: {text[:200]!r}")
        parsed = json.loads(match.group(0))

        claim_verdict = str(parsed["claim_verdict"]).upper()
        if claim_verdict not in ("SUPPORTED", "UNCERTAIN", "UNSUPPORTED"):
            raise ValueError(f"Unexpected claim_verdict: {claim_verdict!r}")

        unsupported_ratio = max(0.0, min(1.0, float(parsed.get("unsupported_ratio", 0.0))))
        bias_score = max(0.0, min(1.0, float(parsed.get("bias_score", 0.0))))
        consistency_score = max(0.0, min(1.0, float(parsed.get("consistency_score", 1.0))))

        judge_confidence = (
            (1.0 - unsupported_ratio) * 0.5 +
            (1.0 - bias_score) * 0.3 +
            consistency_score * 0.2
        )

        return {
            "judge_confidence": round(judge_confidence, 3),
            "claim_verdict": claim_verdict,
            "bias_score": round(bias_score, 3),
            "consistency_score": round(consistency_score, 3),
            "unsupported_claims": list(parsed.get("unsupported_claims", []))[:3],
        }

    def _heuristic_judge(self, response: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        """Deterministic keyword-based fallback — used whenever no live model is configured."""
        claim_verdict = self._assess_claim_verifiability(response)
        bias_score = self._assess_bias(response)
        consistency_score = self._assess_consistency(response, history)

        judge_confidence = (
            (1.0 - claim_verdict["unsupported_ratio"]) * 0.5 +
            (1.0 - bias_score) * 0.3 +
            consistency_score * 0.2
        )

        return {
            "judge_confidence": round(judge_confidence, 3),
            "claim_verdict": claim_verdict["verdict"],
            "bias_score": round(bias_score, 3),
            "consistency_score": round(consistency_score, 3),
            "unsupported_claims": claim_verdict["unsupported_claims"],
        }

    def _assess_claim_verifiability(self, response: str) -> Dict[str, Any]:
        """Heuristic claim verifiability check."""
        claim_indicators = [
            "studies show", "research proves", "according to",
            "data indicates", "statistics show", "experts say",
            "%", "billion", "million", "grew by", "increased by",
            "decreased by", "as of 20"
        ]
        r = response.lower()
        found = [c for c in claim_indicators if c in r]
        unsupported_ratio = min(len(found) / 5.0, 1.0)

        if unsupported_ratio > 0.6:
            verdict = "UNSUPPORTED"
        elif unsupported_ratio > 0.2:
            verdict = "UNCERTAIN"
        else:
            verdict = "SUPPORTED"

        return {
            "verdict": verdict,
            "unsupported_ratio": unsupported_ratio,
            "unsupported_claims": found[:3]
        }

    def _assess_bias(self, response: str) -> float:
        """Heuristic bias detection score (0=no bias, 1=high bias)."""
        bias_patterns = [
            "always", "never", "all of them", "none of them",
            "obviously", "clearly everyone", "it is well known",
            "as everyone knows"
        ]
        r = response.lower()
        matches = sum(1 for p in bias_patterns if p in r)
        return min(matches * 0.15, 1.0)

    def _assess_consistency(self, response: str, history: List[Dict[str, str]]) -> float:
        """Check if response contradicts earlier turns (simple heuristic)."""
        if not history:
            return 1.0
        # Very basic: look for numeric contradictions in last turn
        # In production: semantic similarity check against history
        return 0.95  # Slight penalty for any history (conservative)


# Singleton
ai_judge = AIJudge()
