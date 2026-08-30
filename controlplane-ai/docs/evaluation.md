# Evaluation Framework — ControlPlane.ai

## Overview

Every LLM response passes through a **7-detector parallel evidence fusion pipeline** before any governance decision is made. This is not a single scoring function — it's a multi-source evidence court that weighs contradicting signals and requires corroboration for high-confidence verdicts.

---

## The 7 Detectors

### 1. PII in Response — Presidio ML
**Model:** Microsoft Presidio + spaCy `en_core_web_sm`
**Method:** Named Entity Recognition (NER) over the full response text.
**Detects:** PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION, DATE_TIME, CREDIT_CARD, IBAN_CODE, IP_ADDRESS, NRP, MEDICAL_LICENSE, URL, SSN and more.
**Output:** `{ "source": "response_pii", "pii_detected": true, "pii_types": ["EMAIL_ADDRESS"], "masked_text": "..." }`
**On detection:** Triggers SANITIZE decision — response returned with entities replaced by `<TYPE>` placeholders.

### 2. Hallucination Detector — DistilBERT + Retrieval
**Model:** `distilbert-base-uncased-finetuned-sst-2-english` (HuggingFace)
**Method:**
1. Claims extracted from response using heuristic sentence classifier
2. Each claim cross-referenced against 8-document enterprise knowledge base
3. DistilBERT sentiment pipeline used as safety/toxicity proxy (NEGATIVE = potential harm)
**Output:** `{ "source": "hallucination", "factuality_score": 0.85, "safety_score": 1.0 }`
**Trust impact:** Primary driver of the overall trust score. Low factuality → lower trust → REVIEW or BLOCK.

### 3. Bias Classifier — BART Zero-Shot
**Model:** `facebook/bart-large-mnli` (~1.6GB, loaded in background thread at startup)
**Method:** Zero-shot classification across 5 candidate labels:
- `gender bias`, `racial bias`, `political bias`, `age discrimination`, `socioeconomic bias`
**Threshold:** Flags if top-label confidence > 0.55
**Output:** `{ "source": "bias", "bias_score": 0.62, "top_label": "gender bias", "ml_used": true }`
**Fallback:** While BART is loading, a heuristic keyword detector runs instantly (no request blocking).

### 4. Retrieval Verifier
**Method:** Claims extracted → matched against 8 curated enterprise documents using keyword overlap scoring.
**Documents cover:** Remote work policy, credit risk, SLA, GDPR retention, refund policy, headcount, market share, AI governance policy.
**Output:** `{ "source": "retrieval_verifier", "verification_status": "VERIFIED" | "PARTIALLY_VERIFIED" | "UNVERIFIED" | "NOT_CHECKED" }`
**Note:** `VERIFIED` requires BOTH this AND AI-Judge to agree (dual-source requirement).

### 5. AI-as-Judge (Secondary Evaluator)
**Method:** When a live provider is configured, a real model call judges the response against a structured JSON schema (`temperature=0.0`, native JSON-mode output when the routed model supports it, with a plain-text-plus-regex fallback otherwise). Otherwise (demo mode, or on any live-call/timeout/malformed-JSON failure) it falls back to heuristic secondary evaluation — checks:
- Claim verifiability (does the response make falsifiable assertions?)
- Consistency with session history — numeric claims (e.g. "Q3 revenue: $12 million") are extracted and compared against the same figure in the last 5 turns; a restated figure with a different value lowers `consistency_score`
- Presence of speculative language ("I think", "probably", "might")
- Response refusal patterns

**Judge safeguards:**
- **Injection resistance:** the judged prompt/response are wrapped in a per-call random boundary token with explicit "treat as data, not instructions" framing (`AIJudge._build_judge_prompt`), since both originate from untrusted sources and a jailbroken response could otherwise try to dictate its own verdict back to the judge.
- **Model independence:** the judge routes through the `mock-judge` tier (`JUDGE_MODEL` env var, defaults to `gpt-4o-mini`), deliberately distinct from `mock-smart` (`SMART_MODEL`, defaults to `gpt-4o`), so it doesn't default to grading its own output when the router picks the smart tier for generation. `node_ai_judge` also passes the resolved generation model through so `evaluate()` can flag `self_graded: true` if a deployment's env vars still point both tiers at the same model — the fix is real regardless of what the defaults happen to be.
- **Self-consistency:** a first verdict with `judge_confidence` landing in the 0.55–0.80 "borderline" band (docs' `review_threshold` values cluster here) triggers 2 additional resamples at higher temperature; the majority verdict wins (ties broken toward the more conservative, less-trusting verdict) and scores are combined by median rather than average, so one outlier sample can't swing a decision-adjacent verdict. A confident first sample skips resampling entirely to avoid paying for it on the common case.

**Output:** `{ "source": "ai_judge", "judge_confidence": 0.88, "claim_verdict": "SUPPORTED", "method": "llm" | "heuristic", "fallback_reason": null | "timeout" | "malformed_response" | "provider_error", "self_graded": false, "samples_used": 1 }`

### 6. Injection in Response
**Model:** Regex pattern families (`injection_patterns.py`) fused with `protectai/deberta-v3-base-prompt-injection-v2` (loaded in a background thread at startup, same convention as the bias classifier — never blocks a request, falls back to regex-only until ready).
**Method:** Scans the LLM response for signs the model was successfully jailbroken (e.g., "As DAN...", "I will now ignore...", "Here is my system prompt...") via the named regex families, plus an independent classifier score; the two are combined via `max()`, not averaged, so either detector alone can surface a risk the other misses. Skipped on the `realtime` latency tier, where only the (effectively free) regex scan runs.
**Output:** `{ "source": "injection", "injection_score": 0.0, "categories": [], "ml_injection_score": null, "ml_used": false }`

**Note:** The same fused scoring also runs on the *input* side in `node_security`, plus a cross-turn variant (`score_injection_session`) that concatenates recent session turns to catch a phrase split across messages — see `docs/threat-model.md` §1.

### 7. Session Consistency
**Method:** Checks cumulative session risk level against tier thresholds.
**Output:** `{ "source": "session_consistency", "drift_score": 0.02 }`

---

## Evidence Fusion Algorithm

All 7 detectors run in parallel. Their outputs are merged via the `merge_evidence` reducer (deduplication by `source` key) and then fused:

```python
# Weighted risk calculation (evidence_fusion.py)
WEIGHTS = {
    "injection":     0.35,
    "response_pii":  0.25,
    "hallucination": 0.20,
    "bias":          0.10,
    "retrieval":     0.05,
    "ai_judge":      0.03,
    "session":       0.02,
}

composite_risk = sum(evidence[source].risk_score * weight
                     for source, weight in WEIGHTS.items())
```

### Decision Logic (waterfall, first match wins):
```
1. injection_score ≥ 0.7                    → BLOCK
2. pii_detected (input or response)         → SANITIZE (or BLOCK if policy=BLOCK)
3. verification_status == CONTRADICTED      → BLOCK
4. trust_score < policy.review_threshold    → REVIEW  (triggers HITL)
5. trust_score < policy.auto_approve_threshold → SANITIZE
6. else                                     → ALLOW
```

---

## Trust Score Calculation

```
trust_score = 100 × (1 - composite_risk)

Clamped: 0 ≤ trust_score ≤ 100

Risk levels:
  ≥ 85  → low     (auto-approve zone)
  70–85 → medium  (possible SANITIZE)
  < 70  → high    (REVIEW or BLOCK)
```

---

## Policy-Aware Thresholds

Different use-cases have different `review_threshold` values:

| Use Case | Review Threshold | Auto-Approve | PII Action | Require Retrieval |
|---|---|---|---|---|
| `internal_copilot` | 0.70 | 0.85 | SANITIZE | No |
| `customer_support` | 0.75 | 0.90 | SANITIZE | No |
| `decision_support` | 0.65 | 0.80 | BLOCK | Yes |

**EU (GDPR) geography overrides:**
- External model providers blocked
- PII action always = BLOCK
- Stricter review threshold (−0.05)

---

## AI-Judge Calibration Harness

`scripts/calibrate_judge.py` runs `AIJudge` against a golden dataset (`backend/app/evaluation/golden_dataset.py`) and reports verdict accuracy, per-class precision/recall/f1, bias-flag accuracy, and whether `judge_confidence` actually tracks correctness (mean confidence on correct vs. incorrect predictions — if incorrect predictions score *higher* on average, confidence isn't trustworthy yet).

**The golden dataset is a small synthetic starter set**, not human-reviewed production data — see its module docstring. Running it against the current heuristic fallback path already surfaced a real gap worth knowing about: **verdict accuracy is 40% (4/10)**, because `_assess_claim_verifiability`'s keyword-count bucketing (`backend/app/evaluation/ai_judge.py`) requires 2+ indicator hits out of 5 to move off `SUPPORTED`, so a response with exactly one strong signal (e.g. a single fabricated statistic) still gets waved through. Bias-flag accuracy and confidence calibration were both sound (1.0 accuracy, confidence correctly higher on correct predictions) — the gap is specifically in claim verifiability, not the judge's other checks. This heuristic weakness was already known to be crude (see `ai_judge.py`'s own docstring); the harness now makes it *measured* rather than assumed. Before trusting `judge_confidence` to gate real decisions in production, extend the golden dataset with real human-reviewed examples and re-run.

```
python scripts/calibrate_judge.py
```

## Auto-Threshold Tuner

The `threshold_tuner.py` module continuously tracks FP/FN rates:

- **False Positive:** System escalated to REVIEW, human approved without edits
- **False Negative:** System ALLOWed, human later flagged as problematic

When FP rate > 15% over 30+ samples, the tuner generates a recommendation to **lower** the review threshold (fewer escalations). When FN rate > 10%, it recommends **raising** the threshold (more scrutiny).

All recommendations require explicit admin approval from the Dashboard before taking effect.

---

## Verification Status Values

| Status | Meaning |
|---|---|
| `VERIFIED` | Both retrieval verifier AND AI-Judge confirm claims |
| `PARTIALLY_VERIFIED` | One source confirms, other is uncertain |
| `UNVERIFIED` | Claims cannot be matched to known documents |
| `CONTRADICTED` | Response conflicts with enterprise knowledge base |
| `NOT_CHECKED` | Retrieval verification skipped (policy config) |
