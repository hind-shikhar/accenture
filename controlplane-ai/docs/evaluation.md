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
**Method:** Heuristic secondary evaluation — checks:
- Claim verifiability (does the response make falsifiable assertions?)
- Consistency with session history
- Presence of speculative language ("I think", "probably", "might")
- Response refusal patterns
**Output:** `{ "source": "ai_judge", "judge_confidence": 0.88, "claim_verdict": "SUPPORTED" }`

### 6. Injection in Response
**Method:** Keyword scanning of LLM response for signs the model was successfully jailbroken (e.g., "As DAN...", "I will now ignore...", "Here is my system prompt...")
**Output:** `{ "source": "injection", "injection_score": 0.0 }`

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
