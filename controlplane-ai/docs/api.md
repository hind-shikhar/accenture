# API Reference — ControlPlane.ai

Base URL: `http://localhost:8000/api/v1`

---

## Core Endpoints

### `POST /chat`
Execute a prompt through the full governance pipeline.

**Request Body:**
```json
{
  "prompt": "What is the remote work policy?",
  "use_case": "internal_copilot",
  "geography": "global",
  "session_id": "optional-uuid",
  "sensitivity": "medium",
  "cost_budget": 0.01,
  "proposed_action": null
}
```

| Field | Type | Values | Default |
|---|---|---|---|
| `prompt` | string | Any | required |
| `use_case` | enum | `internal_copilot`, `customer_support`, `decision_support` | `internal_copilot` |
| `geography` | enum | `global`, `eu`, `us` | `global` |
| `session_id` | string | UUID | auto-generated |
| `sensitivity` | enum | `low`, `medium`, `high` | `medium` |
| `cost_budget` | float | 0.0 – 1.0 | `0.01` |

**Response `200 OK`:**
```json
{
  "text": "The company's hybrid work policy allows...",
  "model": "mock-fast",
  "provider": "mock",
  "trust_score": 92.0,
  "risk_level": "low",
  "decision": "ALLOW",
  "verification_status": "VERIFIED",
  "overlapping_risks": [],
  "security": {
    "pii_detected": false,
    "pii_types": [],
    "prompt_injection_score": 0.0,
    "risk_level": "low",
    "allowed": true,
    "actions": []
  },
  "evaluation": {
    "factuality_score": 0.92,
    "safety_score": 1.0
  },
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "660e8400-e29b-41d4-a716-446655440001",
  "sanitized": false
}
```

**Response `403 Forbidden`** (decision = BLOCK):
```json
{
  "detail": {
    "message": "Blocked by policy — prompt injection detected",
    "trace_id": "...",
    "reasons": ["Injection score 0.95 exceeds policy threshold"],
    "decision": "BLOCK"
  }
}
```

**Decision Values:**
| Decision | Meaning |
|---|---|
| `ALLOW` | Response passes all governance checks |
| `SANITIZE` | Response returned with PII masked |
| `REVIEW` | Response queued for human review (HITL) |
| `BLOCK` | Request or response blocked — HTTP 403 raised |

---

### `POST /agent-action`
Evaluate a proposed agent action through the Agentic Risk Gate before execution.

**Request Body:**
```json
{
  "action_type": "delete_record",
  "use_case": "decision_support",
  "session_id": "optional-uuid",
  "parameters": {
    "target": "customer_records",
    "record_id": "12345"
  }
}
```

**Response:**
```json
{
  "action_type": "delete_record",
  "decision": "BLOCK",
  "risk_score": 0.95,
  "reasons": ["Irreversible action requires HITL"],
  "message": "Action BLOCKED by ControlPlane Action Gate. HITL required."
}
```

---

## Dashboard & Audit Endpoints

### `GET /metrics`
Aggregate governance metrics.

**Response:**
```json
{
  "total_requests": 150,
  "escalated_requests": 12,
  "approved_responses": 98,
  "sanitized_responses": 25,
  "blocked_responses": 15,
  "average_trust_score": 84.3,
  "human_override_rate": 0.083,
  "decision_distribution": {
    "ALLOW": 0.65,
    "SANITIZE": 0.17,
    "REVIEW": 0.08,
    "BLOCK": 0.10
  }
}
```

### `GET /audit`
Returns the 50 most recent audit log entries, ordered newest first.

Each entry includes: `id`, `timestamp`, `prompt`, `response_text`, `decision`, `trust_score`, `risk_level`, `use_case`, `geography`, `security_result` (JSON), `evaluation_result` (JSON), `composite_risk` (JSON with `risk_vectors`), `detector_latencies` (JSON), `primary_risk_category`, `verification_status`, `human_review_status`.

### `GET /audit/export`
Downloads all audit logs as a timestamped CSV file.

**Headers returned:** `Content-Disposition: attachment; filename=controlplane_audit_YYYYMMDD_HHMMSS.csv`

---

## Human-in-the-Loop Endpoints

### `GET /reviews`
Returns all audit entries with `human_review_status = "pending"`.

### `POST /review/{log_id}?action={action}`
Submit a human review decision.

| `action` | Effect |
|---|---|
| `approve` | Resumes LangGraph graph — response delivered to original caller |
| `reject` | Resumes graph with rejection — response suppressed |
| `edit` | Resumes graph with `edited_text` replacing the LLM response |
| `regenerate` | Resumes graph — signals LLM to retry |

**Optional body param:** `edited_text` (string) — used with `action=edit`.

---

## Threshold Tuner Endpoints

### `GET /thresholds/recommendations`
Returns pending AI-generated policy threshold recommendations.

**Response:**
```json
[
  {
    "id": "uuid",
    "use_case": "decision_support",
    "current_threshold": 0.7,
    "recommended_threshold": 0.65,
    "reason": "High FP rate (18%) — system over-escalating safe responses",
    "fp_rate": 0.18,
    "sample_size": 45,
    "status": "awaiting_admin_approval"
  }
]
```

### `POST /thresholds/{rec_id}/approve`
Apply the recommended threshold change.

### `POST /thresholds/{rec_id}/reject`
Dismiss the recommendation.

### `POST /thresholds/analyze/{use_case}`
Trigger on-demand FP/FN analysis for a given use case and generate a new recommendation if warranted.

---

## Health Endpoints

### `GET /health`
```json
{ "status": "ok", "timestamp": 1724482800.0 }
```

### `GET /ready`
```json
{ "status": "ready" }
```

### `GET /models/status`
```json
{
  "presidio_pii": "loaded",
  "distilbert_safety": "loaded",
  "bart_bias": "loaded"
}
```
