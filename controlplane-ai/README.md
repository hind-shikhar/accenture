# ControlPlane.ai

> **Accenture Innovation Challenge 2026 — Round 2**
> An enterprise-grade, model-agnostic AI Governance Middleware built on LangGraph.

**🎥 Demo Video:** [Watch the walkthrough](https://drive.google.com/file/d/1t4-ZC3IXH8LWsjHGLSI8SftOSyELeahk/view?usp=drive_link)

---

## Contents

- [What is ControlPlane.ai?](#what-is-controlplaneai)
- [Implementation Approach](#implementation-approach)
- [Round 2 Architecture](#round-2-architecture)
- [Key Features](#key-features)
- [Use Cases Demonstrated](#use-cases-demonstrated)
- [Dependencies](#dependencies)
- [Running the Project](#running-the-project-no-docker-required)
- [Demo Mode](#demo-mode)
- [Project Structure](#project-structure)
- [Future Additions / Roadmap](#future-additions--roadmap)
- [Further Documentation](#further-documentation)

---

## What is ControlPlane.ai?

ControlPlane.ai is a plug-and-play governance layer that sits **between your enterprise application and any AI model**. Every prompt and every response passes through a multi-stage pipeline that enforces security, compliance, fairness, and accountability — in real time, without changing your AI model or application code.

It answers the question enterprises ask every day: *"How do I know if this AI response is safe, factual, and compliant before it reaches my user?"*

---

## Implementation Approach

The brief calls out a set of real-world complexities that make a single, hard-coded "is this response okay?" check unworkable at enterprise scale. Each design decision in ControlPlane.ai traces back to one of them:

| Real-world complexity | How ControlPlane.ai handles it |
|---|---|
| Different use cases have different risk tolerance & latency budgets | A **policy registry** keyed by `use_case` × `geography` sets independent `review_threshold`, `auto_approve_threshold`, and `pii_action` values per use case; the **semantic router** picks a fast/smart/external model per request based on sensitivity and cost budget — customer support isn't held to the same latency bar as decision support |
| Bias, hallucination, and privacy risks overlap in practice | The **evidence fusion engine** never forces a single label onto a response. All 7 detectors run in parallel and their outputs are kept as a set — the composite result exposes both a `primary_risk_category` *and* `overlapping_risks`, so a fabricated personal detail is recorded as hallucination **and** PII, not one or the other |
| No reliable real-time ground truth to check claims against | Retrieval verification is confidence-scored, not binary, and requires **dual-source agreement** (retrieval verifier + AI-judge) before a claim is marked `VERIFIED`. `UNVERIFIED` is a first-class outcome — the system says "can't confirm this" instead of guessing ALLOW or BLOCK |
| Over-flagging causes alert fatigue; under-flagging creates liability | Decisions run on a **4-tier ladder** (ALLOW → SANITIZE → REVIEW → BLOCK) instead of a binary gate, and the **auto-threshold tuner** watches real HITL outcomes (reviewers rubber-stamping REVIEW escalations = false positives; ALLOWed responses later flagged = false negatives) and proposes threshold adjustments — it never re-tunes itself silently, an admin has to approve the change |
| Multi-turn conversations and agents compound risk | The **session risk tracker** accumulates risk drift across a conversation (4-tier escalation, can lock a session outright) instead of scoring every turn in isolation; a separate **Action Risk Gate** scores agent actions before execution and forces human approval on irreversible ones (delete, send, pay) |
| Regulatory expectations vary by geography/industry and keep changing | Policy is **data, not code** — `use_case` and `geography` are lookup keys into a threshold/action table (`backend/app/policies/registry.py`), so a new jurisdiction or vertical is a config change, not a pipeline rewrite |
| Enterprises consume a foundation model via API, not model internals | Every detector operates purely on **prompt/response text at the I/O boundary** — none of it depends on logits, attention, or fine-tuning access — so the same pipeline runs unchanged against a hosted OpenAI/Anthropic API or the local mock provider used in demo mode |

**Where the checker sits (architecture choice):** a hybrid of pre-response gate, inline middleware, and post-hoc audit, rather than picking just one:
- **Pre-response gate** — `node_security` + policy precheck block obvious threats (prompt injection, leaked credentials) *before the LLM is even called*, so no tokens are spent and no risky prompt reaches the model.
- **Inline parallel middleware** — the 6 post-response detectors fan out concurrently via `asyncio` executors and a background thread, so they add latency roughly equal to the *slowest single detector*, not the sum of all seven — protecting the latency budget from complexity #1.
- **Post-hoc audit** — every decision, full evidence breakdown, and per-node latency is written to the audit log regardless of outcome, so compliance review doesn't depend on the real-time path.

---

## Round 2 Architecture

```
User Prompt
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  ControlPlane.ai — LangGraph Orchestration Pipeline             │
│                                                                 │
│  [Security Gate]──►[Session Risk]──►[Semantic Router]──►[LLM]  │
│       │                                                    │    │
│   Presidio ML + DeBERTa v3                 ┌───────────────┤    │
│   PII + Injection (regex ⊔ ML)             │   Parallel    │    │
│                                            │   Detection   │    │
│                              ┌─────────────▼─────────────┐│    │
│                              │  PII in Response           ││    │
│                              │  Hallucination (DistilBERT)││    │
│                              │  Bias (BART zero-shot)     ││    │
│                              │  Retrieval Verifier        ││    │
│                              │  AI-as-Judge               ││    │
│                              │  Injection in Response     ││    │
│                              └─────────────┬─────────────-┘│    │
│                                            │               │    │
│                              ┌─────────────▼──────────────┐│    │
│                              │  Evidence Fusion Engine    ││    │
│                              │  7-source weighted fusion  ││    │
│                              └─────────────┬──────────────┘│    │
│                                            │               │    │
│                    ┌───────────────────────┼──────────┐   │    │
│                    ▼           ▼           ▼          ▼   │    │
│                 ALLOW      SANITIZE     REVIEW      BLOCK  │    │
│                                           │                │    │
│                                    [HITL Queue]            │    │
│                                    Human Approve/Reject    │    │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
Governance Audit Log + Auto-Threshold Tuner
```

---

## Key Features

| Feature | Description |
|---|---|
| **ML-Powered PII Detection** | Microsoft Presidio with spaCy NER — masks PERSON, EMAIL, PHONE, LOCATION, SSN, etc. |
| **BART Zero-Shot Bias Classifier** | `facebook/bart-large-mnli` classifies gender, racial, political, age & socioeconomic bias |
| **DistilBERT Safety Scorer** | HuggingFace sentiment pipeline as a toxicity/safety proxy |
| **Retrieval-Based Hallucination Verification** | Claims cross-referenced against a local enterprise document store |
| **ML Prompt-Injection Classifier** | `protectai/deberta-v3-base-prompt-injection-v2` fused (via `max()`) with the regex pattern families, on both the incoming prompt and the outgoing response — catches injection attempts regex alone misses, without ever downgrading a regex hit |
| **AI-Judge Calibration Harness** | `scripts/calibrate_judge.py` scores the AI-as-Judge detector against a golden dataset (verdict accuracy, per-class precision/recall/f1, and whether `judge_confidence` actually tracks correctness) — plus `scripts/export_reviewed_examples.py` to grow that dataset from real HITL review decisions over time |
| **Evidence Fusion Engine** | 7 parallel detectors → weighted composite risk score → single governance decision |
| **Policy-Aware Routing** | Per use-case, per-geography thresholds (EU GDPR vs. US vs. Global) |
| **Human-in-the-Loop (HITL)** | LangGraph `interrupt()` → approve/reject/edit/regenerate from dashboard |
| **Session Risk Accumulation** | 4-tier session escalation tracks risk drift across multi-turn conversations |
| **Agentic Action Gate** | Pre-execution risk scoring for AI agent actions (irreversible actions require HITL) |
| **Auto-Threshold Tuner** | FP/FN analysis auto-generates policy threshold recommendations for admin approval |
| **Full Audit Trail** | Every decision logged with evidence breakdown, latencies, and HITL outcome |

---

## Use Cases Demonstrated

- **Customer Support (EU GDPR)** — PII in prompts is masked, external models blocked for sensitive data
- **Internal Copilot** — Unverified financial claims trigger HITL review
- **Decision Support** — All responses retrieval-verified against enterprise documents
- **Agentic Workflows** — Irreversible actions (DELETE_RECORD) blocked with mandatory HITL
- **Adversarial** — Prompt injection attacks detected and blocked at the input gate

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Orchestration** | LangGraph v1.2 (StateGraph with parallel fan-out) |
| **Backend** | FastAPI + SQLAlchemy + SQLite |
| **ML Models** | Presidio (spaCy) for PII, HuggingFace Transformers — DistilBERT (safety proxy), BART zero-shot (bias), DeBERTa v3 (prompt-injection) |
| **Frontend** | React 19, Vite, Tailwind CSS v4, Recharts, Lucide |
| **Testing** | Pytest (69 tests) |

---

## Dependencies

**Backend (Python 3.12+)** — pinned in [`backend/requirements.txt`](backend/requirements.txt)
- **API layer:** FastAPI, Uvicorn, Pydantic / Pydantic-Settings
- **Orchestration:** LangGraph, LangGraph-checkpoint(-sqlite), LangChain-core, LiteLLM
- **Persistence:** SQLAlchemy + aiosqlite (SQLite)
- **ML detectors:** Presidio (analyzer + anonymizer) + spaCy `en_core_web_sm` for PII/NER; PyTorch + Transformers for DistilBERT (hallucination/safety), BART zero-shot (bias), and DeBERTa v3 (`protectai/deberta-v3-base-prompt-injection-v2`) for prompt injection — all three Transformer models load in a background thread at startup and never block a request
- **Observability:** structlog, OpenTelemetry (API + SDK + FastAPI instrumentation)
- **Rate limiting:** slowapi
- **Testing:** pytest, pytest-asyncio, httpx

**Frontend (Node.js 20+)** — declared in [`frontend/package.json`](frontend/package.json)
- React 19 + React Router 7, built with Vite 8 and TypeScript
- Tailwind CSS v4 for styling
- Recharts for dashboard visualizations
- lucide-react, clsx, tailwind-merge for UI utilities

**External model APIs (optional):** an `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` are only required if `DEMO_MODE=false` — the default demo configuration uses a local mock provider and needs no paid API access.

**Production infrastructure (optional)** — pinned in [`backend/requirements-optional.txt`](backend/requirements-optional.txt), none required for the demo:
- `psycopg2-binary` + `asyncpg` — swap SQLite for Postgres (`DATABASE_URL`)
- `redis` — back multi-instance session/HITL-escalation state instead of the in-process dict (`REDIS_URL`)
- `langgraph-checkpoint-postgres` — share paused-HITL checkpoint state across replicas instead of a local SQLite file (`CHECKPOINT_BACKEND=postgres`)
- `chromadb` — real embedding-based retrieval instead of the local keyword-matched doc store
- `opentelemetry-exporter-otlp-proto-grpc` — export traces to a real collector instead of the console

---

## Running the Project (No Docker Required)

### Prerequisites
- Python 3.12+
- Node.js 20+

### Backend
```powershell
# 1. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# 2. Install dependencies
pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm

# 3. Start the backend (first startup downloads ML models ~500MB, takes ~60s)
$env:PYTHONPATH = "C:\path\to\controlplane-ai"
python -m uvicorn backend.app.main:app --port 8000
```

### Frontend
```powershell
cd frontend
npm install
npm run dev
```

Then open:
- **Dashboard** → http://localhost:5173/
- **Interactive Policy Tester** → http://localhost:5173/tester

### Running the Demo Script
```powershell
.\venv\Scripts\activate
$env:PYTHONPATH = "C:\path\to\controlplane-ai"
$env:PYTHONIOENCODING = "utf-8"
python scripts/run_demo.py
```

### Running Tests
```powershell
.\venv\Scripts\activate
$env:PYTHONPATH = "C:\path\to\controlplane-ai"
python -m pytest backend/tests/ -v
```

---

## Demo Mode

The application runs in `DEMO_MODE=true` (default). This means:
- All AI responses come from a local mock provider with 12 realistic enterprise canned responses
- No paid API keys required
- ML models run locally: Presidio, DistilBERT, BART zero-shot, DeBERTa v3 (prompt-injection)

To use a real LLM, set `DEMO_MODE=false` in `.env` and provide your `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.

---

## Project Structure

```
controlplane-ai/
├── backend/
│   └── app/
│       ├── api/          # FastAPI routes (chat, dashboard, metrics)
│       ├── evaluation/   # Evidence fusion, evaluator, AI judge, retrieval verifier,
│       │                 # threshold tuner, judge calibration + golden dataset
│       ├── security/     # Presidio ML scanner + injection pattern families
│       ├── workflows/    # LangGraph state graph (DeBERTa injection classifier lives here)
│       ├── policies/     # Per use-case, per-geography policy registry
│       ├── routing/      # Semantic router
│       ├── session/      # Session risk tracking
│       └── providers/    # LLM provider abstraction (Mock, OpenAI, Anthropic)
├── frontend/
│   └── src/
│       ├── Dashboard.tsx # Governance dashboard with charts
│       ├── Tester.tsx    # Interactive policy tester
│       └── ui.tsx        # Shared UI primitives (panels, section labels, form controls)
├── scripts/
│   ├── run_demo.py       # E2E 5-scenario demo
│   ├── seed_demo_data.py # Populate dashboard with demo data
│   ├── interactive.py    # Interactive CLI tester
│   ├── calibrate_judge.py           # AI-Judge accuracy/calibration report vs. golden dataset
│   └── export_reviewed_examples.py  # Grow the golden dataset from real HITL decisions
└── backend/tests/        # 69 Pytest unit tests (AI judge, judge calibration, ML injection classifier, etc.)
```

---

## Future Additions / Roadmap

ControlPlane.ai is designed to scale with enterprise needs. Round 2 already replaced one detector's generic ML fallback with a purpose-built model — the prompt-injection classifier now runs `protectai/deberta-v3-base-prompt-injection-v2` fused with the regex pattern families, and the AI-as-Judge detector has its own calibration harness (`scripts/calibrate_judge.py`) to measure accuracy against a golden dataset before it's trusted to gate real decisions. The same pattern — a specialized model per detection task, measured against labeled data before it's trusted — is the direction for the rest of the pipeline:

1. **Dedicated, fine-tuned models per detection task.** Each of the remaining generic ML fallbacks gets replaced with a small model fine-tuned for its specific job, the same way prompt-injection detection already moved off pure regex:
   - **Hallucination/factuality** — replace DistilBERT's sentiment-as-safety-proxy with a claim-verification model (e.g. a fine-tuned NLI/entailment model) trained on enterprise-domain text, instead of leaning on retrieval-verifier + AI-judge agreement alone.
   - **Bias/fairness** — fine-tune BART's zero-shot classifier (or a smaller distilled model) on labeled examples from this domain, rather than relying on generic zero-shot labels for gender/racial/political/socioeconomic bias.
   - **Toxicity/safety** — swap the DistilBERT sentiment proxy for a model actually trained for toxicity/harassment classification.
   - **PII** — extend Presidio's spaCy NER with a fine-tuned NER model for entity types and locales the default `en_core_web_sm` model misses (non-English names/addresses, industry-specific identifiers).
   - Each rollout follows the injection classifier's playbook: load in a background thread so it never blocks a request, fuse (never replace) the existing signal, and fall back cleanly if the model isn't ready.
2. **AI-Judge calibration against real data.** `backend/app/evaluation/golden_dataset.py` is currently a small synthetic starter set. `scripts/export_reviewed_examples.py` already exists to turn real HITL approve/reject decisions into golden examples — the roadmap item is running that pipeline continuously in production and using the resulting accuracy/calibration numbers to decide when `judge_confidence` is trustworthy enough to gate REVIEW/BLOCK decisions autonomously.
3. **Embedding-based retrieval.** Move hallucination verification off the local keyword-matched document store and onto real vector search (`chromadb` is already an optional dependency) for semantically-aware — not just keyword-aware — claim verification against enterprise documents.
4. **Semantic Caching & Fast-Pathing:** Cache verified-safe responses for identical or semantically similar queries to cut LLM cost and latency.
5. **Enterprise IAM & RBAC Integration:** Connect the dashboard and HITL queue to enterprise identity providers (OAuth/SAML) for strict role-based access control.
6. **Multi-Modal Governance Expansion:** Extend the Security Gate to scan and sanitize image and audio inputs/outputs for PII, compliance, and NSFW content.
7. **Real-time Streaming Governance:** Emit chunked token streams to the end user while governance checks run in parallel, revoking the stream mid-flight if a violation is detected.

---

## Further Documentation

- [`docs/architecture.md`](docs/architecture.md) — full pipeline breakdown, LangGraph flow diagram, request lifecycle, database schema
- [`docs/evaluation.md`](docs/evaluation.md) — the 7-detector evidence fusion algorithm, trust score math, decision waterfall, threshold-tuning logic
- [`docs/threat-model.md`](docs/threat-model.md) — threat categories, mitigations, and known residual risks (including the demo-only auth stub)
- [`docs/demo.md`](docs/demo.md) — the judge walkthrough script used to record the demo video above
- [`docs/api.md`](docs/api.md) — API reference
- [`docs/developer-guide.md`](docs/developer-guide.md) — developer setup and contribution notes
