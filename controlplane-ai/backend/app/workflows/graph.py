"""
Master LangGraph StateGraph — owns the complete request lifecycle.
Parallel detection nodes → Evidence Fusion → Policy Engine → ALLOW/SANITIZE/REVIEW/BLOCK
"""
import time
import os
import aiosqlite
import asyncio
import operator
from typing import TypedDict, Annotated, Dict, Any, List, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Architecture 3: Persistent State Management
# Defaults to a SQLite-backed checkpointer so a paused HITL review (or any
# in-flight graph state) survives a server restart — MemorySaver loses all
# of that on process exit, silently orphaning any audit row still marked
# human_review_status="pending". Tests force CHECKPOINT_BACKEND=memory via
# conftest.py for isolation and speed. CHECKPOINT_BACKEND=postgres is the
# path for a multi-instance deployment (SQLite-file state can't be shared
# across replicas) — see init_persistent_checkpointer below. It requires the
# optional langgraph-checkpoint-postgres + asyncpg packages (requirements-
# optional.txt) and a running Postgres instance; neither is exercised by
# default, so this never affects the SQLite/memory paths when unconfigured.
#
# NOTE: the sync SqliteSaver's aget/aput raise NotImplementedError in this
# langgraph-checkpoint-sqlite version — the async graph needs AsyncSqliteSaver
# + aiosqlite. AsyncSqliteSaver's connection is bound to whichever event loop
# is running when it's opened, so it CANNOT be created at import time via a
# throwaway asyncio.run() — every call from the real (uvicorn) event loop
# would then hang waiting on a callback queued against an already-closed
# loop. It must be created on the same loop that will run the graph, hence
# the explicit init_persistent_checkpointer() call from main.py's startup
# event below, compiled in with a MemorySaver placeholder until then.
checkpointer = MemorySaver()
_sqlite_checkpoint_conn = None
_postgres_checkpointer_cm = None  # holds the AsyncPostgresSaver context manager open for process lifetime


async def init_persistent_checkpointer():
    """Swap in a persistent checkpointer. Must be awaited from the event
    loop that will actually serve requests (e.g. FastAPI startup)."""
    global _sqlite_checkpoint_conn, _postgres_checkpointer_cm
    backend_kind = os.getenv("CHECKPOINT_BACKEND", "sqlite")
    if backend_kind == "memory":
        return

    if backend_kind == "postgres":
        pg_conn_str = os.getenv("CHECKPOINT_DB_URL")
        if not pg_conn_str:
            logger.error("checkpoint_backend_postgres_missing_url",
                         detail="CHECKPOINT_BACKEND=postgres requires CHECKPOINT_DB_URL — falling back to SQLite")
        else:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                _postgres_checkpointer_cm = AsyncPostgresSaver.from_conn_string(pg_conn_str)
                saver = await _postgres_checkpointer_cm.__aenter__()
                await saver.setup()
                app_graph.checkpointer = saver
                logger.info("persistent_checkpointer_initialized", backend="postgres")
                return
            except ImportError:
                logger.error("checkpoint_backend_postgres_not_installed",
                             detail="pip install langgraph-checkpoint-postgres asyncpg — falling back to SQLite")
            except Exception as e:
                logger.error("checkpoint_backend_postgres_init_failed", error=str(e), fallback="sqlite")

    db_path = os.getenv("CHECKPOINT_DB_PATH", "langgraph_state.db")
    _sqlite_checkpoint_conn = await aiosqlite.connect(db_path)
    saver = AsyncSqliteSaver(_sqlite_checkpoint_conn)
    await saver.setup()
    app_graph.checkpointer = saver
    logger.info("persistent_checkpointer_initialized", backend="sqlite", db_path=db_path)

from backend.app.security.scanner import SecurityScanner
from backend.app.security.injection_patterns import score_injection, score_injection_session
from backend.app.routing.router import SemanticRouter
from backend.app.providers.factory import ProviderFactory
from backend.app.evaluation.evaluator import ResponseEvaluator
from backend.app.evaluation.ai_judge import ai_judge
from backend.app.evaluation.retrieval_verifier import retrieval_verifier
from backend.app.evaluation.evidence_fusion import evidence_fusion
from backend.app.policies.registry import policy_registry
from backend.app.session.context import session_store
from backend.app.schemas.chat import ChatRequest, Decision
from backend.app.costs import pricing

import structlog
logger = structlog.get_logger()

# ─── Latency Tiers ────────────────────────────────────────────────────────────
# Per-detector timeout budget (ms) by policy.latency_tier. A detector that
# blows its budget is aborted and falls back to a conservative heuristic
# result rather than stalling the whole request — this is what lets a
# customer-facing (realtime) use case share the same 7-detector pipeline as a
# batch/regulated one without inheriting its worst-case latency.
TIER_ML_TIMEOUT_MS = {"realtime": 300, "standard": 1200, "batch": 4000}

# ─── ML Model: Zero-Shot Bias Classifier ─────────────────────────────────────
# Loaded in a background thread at startup (main.py).
# Requests NEVER wait for this — they fall back to heuristics if not ready.
import threading as _threading
_bias_classifier = None
_bias_ready = _threading.Event()


def _get_bias_classifier():
    """Returns the classifier only if already loaded. Never blocks."""
    return _bias_classifier if _bias_ready.is_set() else None


def _load_bias_classifier_background():
    """
    Called from main.py startup in a daemon thread.
    Downloads and loads facebook/bart-large-mnli once, then signals ready.
    """
    global _bias_classifier
    try:
        from transformers import pipeline
        logger.info("Loading zero-shot bias classifier (facebook/bart-large-mnli)...")
        clf = pipeline(
            "zero-shot-classification",
            model="facebook/bart-large-mnli",
            device=-1  # CPU
        )
        _bias_classifier = clf
        _bias_ready.set()
        logger.info("Bias classifier loaded and ready.")
    except Exception as e:
        logger.warning(f"Bias classifier load failed: {e}. Heuristics will be used.")
        _bias_classifier = "fallback"
        _bias_ready.set()  # Signal ready so we don't re-attempt per request


# ─── ML Model: Prompt-Injection Classifier ───────────────────────────────────
# Loaded in a background thread at startup (main.py), same convention as the
# bias classifier above. score_injection() (injection_patterns.py) only ever
# catches phrasing inside its named pattern families — this trained
# classifier is a second, independent signal that can catch paraphrases
# outside those families. It is fused via max() with the regex score in
# node_security / node_detect_injection_in_response, never a replacement —
# same defense-in-depth reasoning as everywhere else in this pipeline: no
# single detector is trusted as the sole source of a BLOCK.
_injection_classifier = None
_injection_ready = _threading.Event()


def _get_injection_classifier():
    """Returns the classifier only if already loaded. Never blocks."""
    return _injection_classifier if _injection_ready.is_set() else None


def _load_injection_classifier_background():
    """
    Called from main.py startup in a daemon thread.
    Downloads and loads protectai/deberta-v3-base-prompt-injection-v2 once,
    then signals ready.
    """
    global _injection_classifier
    try:
        from transformers import pipeline
        logger.info("Loading prompt-injection classifier (protectai/deberta-v3-base-prompt-injection-v2)...")
        clf = pipeline(
            "text-classification",
            model="protectai/deberta-v3-base-prompt-injection-v2",
            device=-1  # CPU
        )
        _injection_classifier = clf
        _injection_ready.set()
        logger.info("Injection classifier loaded and ready.")
    except Exception as e:
        logger.warning(f"Injection classifier load failed: {e}. Regex-only scoring will be used.")
        _injection_classifier = "fallback"
        _injection_ready.set()  # Signal ready so we don't re-attempt per request


async def _ml_injection_score(text: str, latency_tier: str) -> "tuple[float, bool]":
    """Returns (score, ml_used). Never blocks past the tier's ML timeout
    budget, and never raises — any failure just means the regex score
    stands alone, the same fail-open posture as the bias classifier."""
    if latency_tier == "realtime" or not _injection_ready.is_set() \
            or _injection_classifier in (None, "fallback") or not text.strip():
        return 0.0, False
    try:
        trunc = text[:2000]
        loop = asyncio.get_event_loop()
        timeout_s = TIER_ML_TIMEOUT_MS.get(latency_tier, 1200) / 1000
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _injection_classifier(trunc, truncation=True)[0]),
            timeout=timeout_s,
        )
        label = str(result.get("label", "")).upper()
        confidence = float(result.get("score", 0.0))
        # Label text varies by model version ("INJECTION" vs "SAFE" etc.) —
        # treat confidence as an injection score only when the label itself
        # says so, otherwise it's confidence in SAFETY and the injection
        # score is its complement.
        ml_score = confidence if "INJECT" in label or "UNSAFE" in label else (1.0 - confidence)
        return round(ml_score, 3), True
    except asyncio.TimeoutError:
        logger.warning("injection_ml_timeout", latency_tier=latency_tier, budget_ms=TIER_ML_TIMEOUT_MS.get(latency_tier))
        return 0.0, False
    except Exception as e:
        logger.warning(f"Injection ML inference error: {e}")
        return 0.0, False


# Instances
scanner = SecurityScanner()
semantic_router = SemanticRouter()
evaluator = ResponseEvaluator()


# Safe reducers for parallel node outputs
def merge_dicts(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    merged = a.copy()
    if b:
        merged.update(b)
    return merged

def merge_lists(a: List[str], b: List[str]) -> List[str]:
    return a + (b if b else [])

def merge_evidence(a: List[Dict], b: List[Dict]) -> List[Dict]:
    seen_sources = {e.get("source") for e in a}
    new_items = [e for e in (b or []) if e.get("source") not in seen_sources]
    return a + new_items


class ControlPlaneState(TypedDict):
    # Request context
    request_id: str
    prompt: str
    cost_budget: float
    sensitivity: str
    use_case: str
    geography: str
    session_id: Optional[str]
    proposed_action: Optional[str]

    # Processing
    masked_prompt: str
    security_result: Dict[str, Any]
    selected_provider: str
    selected_model: str
    llm_response: str
    generation_model_resolved: str

    # Parallel evidence collection (reducer ensures safe merging)
    evidence: Annotated[List[Dict[str, Any]], merge_evidence]
    detector_latencies: Annotated[Dict[str, float], merge_dicts]
    detector_costs: Annotated[Dict[str, float], merge_dicts]

    # Composite assessment
    trust_score: float
    primary_risk_category: str
    overlapping_risks: List[str]
    verification_status: str
    decision: str
    reasons: Annotated[List[str], merge_lists]

    # Session
    session_escalation: str
    cumulative_session_risk: float
    turn_number: int

    # Outputs
    human_decision: str
    final_output: str
    sanitized_response: Optional[str]
    error: str


# ─── Nodes ────────────────────────────────────────────────────────────────────

async def node_security(state: ControlPlaneState):
    t0 = time.time()
    masked, res = await scanner.scan_input(state["prompt"])
    sec_dict = res.model_dump()
    sec_dict["masked_text"] = masked
    sec_dict["source"] = "security_scan"

    # Catches instruction-smuggling split across turns (e.g. "...ignore all"
    # in one message, "previous instructions..." in the next), which the
    # single-message scan above can't see. session_store already holds
    # prior turns' prompts by the time this request arrives — add_turn() for
    # THIS request only happens after the graph completes (api/chat.py).
    session_id = state.get("session_id")
    if session_id:
        session = await session_store.get(session_id)
        if session:
            recent_prompts = [t.prompt for t in session.turns[-4:]]
            cross_turn_score, cross_turn_categories = score_injection_session(state["prompt"], recent_prompts)
            if cross_turn_score > 0:
                sec_dict["cross_turn_injection_score"] = cross_turn_score
                sec_dict["cross_turn_injection_categories"] = cross_turn_categories
                sec_dict["prompt_injection_score"] = max(sec_dict["prompt_injection_score"], cross_turn_score)
                sec_dict["allowed"] = sec_dict["prompt_injection_score"] < 0.7
                logger.warning("cross_turn_injection_detected", session_id=session_id,
                                categories=cross_turn_categories, score=cross_turn_score)

    # Second, independent signal beyond the regex pattern families — see
    # _ml_injection_score above. Fused via max(), never a replacement.
    policy = policy_registry.get_policy(state.get("use_case", "internal_copilot"), state.get("geography", "global"))
    ml_score, ml_used = await _ml_injection_score(state["prompt"], policy.latency_tier)
    if ml_used:
        sec_dict["ml_injection_score"] = ml_score
        sec_dict["prompt_injection_score"] = max(sec_dict["prompt_injection_score"], ml_score)
        sec_dict["allowed"] = sec_dict["prompt_injection_score"] < 0.7

    latency = (time.time() - t0) * 1000
    return {
        "masked_prompt": masked,
        "security_result": sec_dict,
        "evidence": [sec_dict],
        "detector_latencies": {"security_scan": round(latency, 2)},
        "detector_costs": {"security_scan": pricing.estimate_detector_cost("security_scan", ml_used=ml_used)}
    }


async def node_policy_precheck(state: ControlPlaneState):
    sec = state.get("security_result", {})
    reasons = []
    decision = None

    injection_score = sec.get("prompt_injection_score", 0.0)
    # also check allowed flag set by scanner
    if injection_score >= 0.7 or not sec.get("allowed", True):
        reasons.append("Prompt injection detected at input gate")
        decision = "BLOCK"
    elif sec.get("risk_level") == "high":
        reasons.append("High-risk security violation at input gate")
        decision = "BLOCK"
    if decision:
        return {"decision": decision, "reasons": reasons, "final_output": "Request blocked by security policy."}
    return {}


async def node_session_check(state: ControlPlaneState):
    session_id = state.get("session_id")
    if not session_id:
        return {"session_escalation": "normal", "cumulative_session_risk": 0.0, "turn_number": 1}

    use_case = state.get("use_case", "internal_copilot")
    geography = state.get("geography", "global")
    policy = policy_registry.get_policy(use_case, geography)
    session = await session_store.get_or_create(session_id, use_case, policy.session_escalation_thresholds)
    drift = await session_store.get_drift_score(session_id)

    return {
        "session_escalation": session.escalation_level,
        "cumulative_session_risk": session.cumulative_risk,
        "turn_number": session.turn_count + 1,
        "evidence": [{"source": "session_consistency", "drift_score": drift,
                      "cumulative_risk": session.cumulative_risk,
                      "escalation_level": session.escalation_level}]
    }


async def node_router(state: ControlPlaneState):
    req = ChatRequest(
        prompt=state["prompt"],
        cost_budget=state.get("cost_budget", 0.01),
        sensitivity=state.get("sensitivity", "medium"),
        use_case=state.get("use_case", "internal_copilot"),
        geography=state.get("geography", "global")
    )
    res = await semantic_router.route(req)

    policy = policy_registry.get_policy(state.get("use_case", "internal_copilot"), state.get("geography", "global"))
    sec = state.get("security_result", {})
    if sec.get("pii_detected") and not policy.allow_external_models:
        return {"decision": "BLOCK", "reasons": ["PII detected + external model not allowed by policy"]}

    return {"selected_model": res.selected_model, "selected_provider": res.provider}


async def node_llm(state: ControlPlaneState):
    provider = ProviderFactory.get_provider(state.get("selected_provider", "mock"))
    try:
        t0 = time.time()
        model_id = state.get("selected_model", "mock-fast")
        model_response = await provider.generate(state["masked_prompt"], model_id)
        latency = (time.time() - t0) * 1000
        response_text = model_response["text"]

        if not response_text.strip():
            return {"error": "empty_response", "decision": "BLOCK", "reasons": ["LLM provider returned empty response"], "final_output": "Provider failed to generate text."}

        usage = model_response.get("usage", {})
        llm_cost = pricing.estimate_llm_cost(
            model_id, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        )
        return {
            "llm_response": response_text,
            "generation_model_resolved": model_response.get("model"),
            "detector_latencies": {"llm": round(latency, 2)},
            "detector_costs": {"llm": llm_cost}
        }
    except Exception as e:
        logger.error("llm_provider_failed", error=str(e), request_id=state.get("request_id"), exc_info=True)
        return {"error": str(e), "decision": "BLOCK", "reasons": ["Provider failure"],
                "final_output": "Upstream model failed."}


# ─── Parallel Detection Nodes ─────────────────────────────────────────────────

async def node_detect_pii_in_response(state: ControlPlaneState):
    """Check if LLM response itself contains PII."""
    t0 = time.time()
    masked, res = await scanner.scan_input(state.get("llm_response", ""))
    latency = (time.time() - t0) * 1000
    ev = res.model_dump()
    ev["masked_text"] = masked
    ev["source"] = "response_pii"
    return {
        "evidence": [ev],
        "detector_latencies": {"response_pii": round(latency, 2)},
        "detector_costs": {"response_pii": pricing.estimate_detector_cost("response_pii")}
    }


async def node_detect_hallucination(state: ControlPlaneState):
    t0 = time.time()
    policy = policy_registry.get_policy(state.get("use_case", "internal_copilot"), state.get("geography", "global"))
    timeout_s = TIER_ML_TIMEOUT_MS.get(policy.latency_tier, 1200) / 1000
    timed_out = False
    try:
        res = await asyncio.wait_for(
            evaluator.evaluate(state.get("masked_prompt", ""), state.get("llm_response", "")),
            timeout=timeout_s
        )
        factuality_score, safety_score = res.factuality_score, res.safety_score
    except asyncio.TimeoutError:
        # Conservative fallback so a slow model call never stalls the whole request.
        timed_out = True
        factuality_score, safety_score = 0.85, 1.0
        logger.warning("hallucination_detector_timeout", tier=policy.latency_tier, budget_ms=TIER_ML_TIMEOUT_MS.get(policy.latency_tier))
    latency = (time.time() - t0) * 1000
    ev = {"source": "hallucination", "factuality_score": factuality_score, "safety_score": safety_score, "timed_out": timed_out}
    return {
        "evidence": [ev],
        "detector_latencies": {"hallucination": round(latency, 2)},
        "detector_costs": {"hallucination": pricing.estimate_detector_cost("hallucination")}
    }


async def node_detect_bias(state: ControlPlaneState):
    t0 = time.time()
    response = state.get("llm_response", "")
    bias_score = 0.0
    top_label = "none"
    markers = []
    ml_used = False

    policy = policy_registry.get_policy(state.get("use_case", "internal_copilot"), state.get("geography", "global"))
    # Realtime tier (customer-facing chat) never pays for BART inference — the
    # 0.10 fusion weight on bias doesn't justify a multi-hundred-ms CPU classifier
    # call at high volume, so it always uses the instant heuristic path.
    ml_allowed_for_tier = policy.latency_tier != "realtime"

    # Only use ML if the model is already loaded (non-blocking check) AND the tier allows it
    if ml_allowed_for_tier and _bias_ready.is_set() and _bias_classifier not in (None, "fallback") and response.strip():
        try:
            bias_labels = [
                "gender bias", "racial bias", "political bias",
                "age discrimination", "socioeconomic bias"
            ]
            trunc = response[:1200]
            loop = asyncio.get_event_loop()
            timeout_s = TIER_ML_TIMEOUT_MS.get(policy.latency_tier, 1200) / 1000
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: _bias_classifier(trunc, candidate_labels=bias_labels, multi_label=False)
                ),
                timeout=timeout_s
            )
            top_label = result["labels"][0]
            top_conf = result["scores"][0]
            bias_score = round(top_conf, 3) if top_conf > 0.55 else 0.0
            if bias_score > 0:
                markers = [f"{top_label} (conf={top_conf:.2f})"]
            ml_used = True
        except asyncio.TimeoutError:
            logger.warning("bias_detector_timeout", tier=policy.latency_tier, budget_ms=TIER_ML_TIMEOUT_MS.get(policy.latency_tier))
        except Exception as e:
            logger.warning(f"Bias ML inference error: {e}")

    if not ml_used:
        # Instant heuristic fallback — zero wait time
        bias_patterns = [
            "always", "never", "all of them", "none of them",
            "obviously", "clearly everyone", "it is well known", "as everyone knows"
        ]
        matches = [p for p in bias_patterns if p in response.lower()]
        bias_score = min(len(matches) * 0.15, 1.0)
        markers = matches[:3]

    latency = (time.time() - t0) * 1000
    return {
        "evidence": [{
            "source": "bias",
            "bias_score": round(bias_score, 3),
            "top_label": top_label,
            "markers": markers,
            "ml_used": ml_used
        }],
        "detector_latencies": {"bias": round(latency, 2)},
        "detector_costs": {"bias": pricing.estimate_detector_cost("bias", ml_used=ml_used)}
    }



async def node_retrieval_verify(state: ControlPlaneState):
    t0 = time.time()
    use_case = state.get("use_case", "internal_copilot")
    policy = policy_registry.get_policy(use_case, state.get("geography", "global"))
    if not policy.require_retrieval_verification:
        return {"evidence": [{"source": "retrieval_verifier", "verification_status": "NOT_CHECKED"}],
                "detector_latencies": {"retrieval": 0.0},
                "detector_costs": {"retrieval": 0.0}}
    ev = await retrieval_verifier.verify(state.get("llm_response", ""))
    latency = (time.time() - t0) * 1000
    ev["latency_ms"] = round(latency, 2)
    return {
        "evidence": [ev],
        "detector_latencies": {"retrieval": round(latency, 2)},
        "detector_costs": {"retrieval": pricing.estimate_detector_cost("retrieval")}
    }


async def node_ai_judge(state: ControlPlaneState):
    t0 = time.time()
    use_case = state.get("use_case", "internal_copilot")
    policy = policy_registry.get_policy(use_case, state.get("geography", "global"))
    session_risk = state.get("cumulative_session_risk", 0.0)

    # Only invoke judge if session risk is elevated or policy requires it
    if session_risk < policy.require_ai_judge_above_session_risk and use_case != "decision_support":
        return {"evidence": [{"source": "ai_judge", "judge_confidence": 1.0, "claim_verdict": "SUPPORTED",
                               "bias_score": 0.0, "skipped": True}],
                "detector_latencies": {"ai_judge": 0.0},
                "detector_costs": {"ai_judge": 0.0}}

    session_id = state.get("session_id")
    history = []
    if session_id:
        session = await session_store.get(session_id)
        if session:
            history = session.get_history()

    # AIJudge's own internal timeout (LIVE_JUDGE_TIMEOUT_S, ai_judge.py) is a
    # flat 8s regardless of use-case tier — far beyond a realtime tier's
    # whole request budget (e.g. 300ms). Enforce the same per-tier ceiling
    # every other ML-backed node in this graph respects, so a slow/borderline
    # live judge call can never blow a realtime SLA; falls back to a
    # conservative UNCERTAIN verdict on timeout rather than stalling.
    timeout_s = TIER_ML_TIMEOUT_MS.get(policy.latency_tier, 1200) / 1000
    try:
        ev = await asyncio.wait_for(
            ai_judge.evaluate(
                state.get("masked_prompt", ""), state.get("llm_response", ""), history,
                generation_model=state.get("generation_model_resolved"),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("ai_judge_node_timeout", tier=policy.latency_tier, budget_ms=TIER_ML_TIMEOUT_MS.get(policy.latency_tier))
        ev = {"source": "ai_judge", "judge_confidence": 0.7, "claim_verdict": "UNCERTAIN",
              "bias_score": 0.0, "consistency_score": 0.7, "unsupported_claims": [],
              "method": "timeout_fallback", "timed_out": True}
    latency = (time.time() - t0) * 1000
    ev["latency_ms"] = round(latency, 2)
    return {
        "evidence": [ev],
        "detector_latencies": {"ai_judge": round(latency, 2)},
        "detector_costs": {"ai_judge": pricing.estimate_detector_cost("ai_judge")}
    }


async def node_detect_injection_in_response(state: ControlPlaneState):
    """Secondary injection check on LLM output (in case model was jailbroken)."""
    t0 = time.time()
    response = state.get("llm_response", "")
    score, categories = score_injection(response)

    policy = policy_registry.get_policy(state.get("use_case", "internal_copilot"), state.get("geography", "global"))
    ml_score, ml_used = await _ml_injection_score(response, policy.latency_tier)
    if ml_used:
        score = max(score, ml_score)

    latency = (time.time() - t0) * 1000
    ev = {"source": "injection", "injection_score": round(score, 3), "categories": categories,
          "ml_injection_score": ml_score if ml_used else None, "ml_used": ml_used}
    return {
        "evidence": [ev],
        "detector_latencies": {"injection": round(latency, 2)},
        "detector_costs": {"injection": pricing.estimate_detector_cost("injection", ml_used=ml_used)}
    }


# ─── Evidence Fusion & Policy ──────────────────────────────────────────────────

async def node_evidence_fusion(state: ControlPlaneState):
    use_case = state.get("use_case", "internal_copilot")
    geography = state.get("geography", "global")
    policy = policy_registry.get_policy(use_case, geography)

    assessment = evidence_fusion.fuse(
        evidence_list=state.get("evidence", []),
        policy=policy,
        session_escalation=state.get("session_escalation", "normal")
    )

    return {
        "trust_score": assessment.trust_score,
        "primary_risk_category": assessment.primary_risk_category,
        "overlapping_risks": assessment.overlapping_risks,
        "verification_status": assessment.verification_status.value,
        "decision": assessment.decision.value,
        "reasons": assessment.reasons,
        "sanitized_response": assessment.sanitized_response,
        "risk_vectors": {k: float(v) for k, v in assessment.risk_vectors.items()},
    }


# ─── HITL, Approve, Block ──────────────────────────────────────────────────────

def node_human_review(state: ControlPlaneState):
    action = interrupt({"message": "Human review required", "state": {
        "trust_score": state.get("trust_score"),
        "decision": state.get("decision"),
        "reasons": state.get("reasons"),
        "verification_status": state.get("verification_status"),
        "overlapping_risks": state.get("overlapping_risks"),
    }})
    human_action = action.get("action")
    edited_text = action.get("text", "")

    if human_action == "approve":
        return {"human_decision": "approve", "final_output": state.get("llm_response", ""), "decision": "ALLOW"}
    elif human_action == "reject":
        return {"human_decision": "reject", "decision": "BLOCK", "final_output": "Rejected by human reviewer."}
    elif human_action == "edit":
        return {"human_decision": "edit", "final_output": edited_text, "decision": "ALLOW"}
    elif human_action == "regenerate":
        return {"human_decision": "regenerate"}
    return {"human_decision": "unknown"}


def node_sanitize(state: ControlPlaneState):
    sanitized = state.get("sanitized_response") or state.get("llm_response", "")
    return {"final_output": sanitized, "decision": "SANITIZE"}


def node_allow(state: ControlPlaneState):
    output = state.get("final_output") or state.get("llm_response", "")
    return {"final_output": output, "decision": "ALLOW"}


def node_block(state: ControlPlaneState):
    return {"final_output": state.get("final_output", "Request blocked by ControlPlane policy."),
            "decision": "BLOCK"}


# ─── Conditional Edges ────────────────────────────────────────────────────────

def conditional_after_precheck(state: ControlPlaneState):
    if state.get("decision") == "BLOCK":
        return "node_block"
    return "node_session_check"


def conditional_after_router(state: ControlPlaneState):
    if state.get("decision") == "BLOCK":
        return "node_block"
    return "node_llm"


def conditional_after_llm(state: ControlPlaneState):
    if state.get("error") or state.get("decision") == "BLOCK":
        return ["node_block"]
    return ["node_detect_pii_in_response", "node_detect_hallucination", "node_detect_bias",
            "node_retrieval_verify", "node_ai_judge", "node_detect_injection_in_response"]


def conditional_after_fusion(state: ControlPlaneState):
    decision = state.get("decision", "ALLOW")
    if decision == "BLOCK":
        return "node_block"
    elif decision == "SANITIZE":
        return "node_sanitize"
    elif decision == "REVIEW":
        return "node_human_review"
    return "node_allow"


def conditional_after_human(state: ControlPlaneState):
    if state.get("human_decision") == "regenerate":
        return "node_llm"
    if state.get("human_decision") == "reject":
        return "node_block"
    return "node_allow"


# ─── Build Graph ──────────────────────────────────────────────────────────────

builder = StateGraph(ControlPlaneState)

builder.add_node("node_security", node_security)
builder.add_node("node_policy_precheck", node_policy_precheck)
builder.add_node("node_session_check", node_session_check)
builder.add_node("node_router", node_router)
builder.add_node("node_llm", node_llm)

# Parallel detection nodes
builder.add_node("node_detect_pii_in_response", node_detect_pii_in_response)
builder.add_node("node_detect_hallucination", node_detect_hallucination)
builder.add_node("node_detect_bias", node_detect_bias)
builder.add_node("node_retrieval_verify", node_retrieval_verify)
builder.add_node("node_ai_judge", node_ai_judge)
builder.add_node("node_detect_injection_in_response", node_detect_injection_in_response)

builder.add_node("node_evidence_fusion", node_evidence_fusion)
builder.add_node("node_human_review", node_human_review)
builder.add_node("node_sanitize", node_sanitize)
builder.add_node("node_allow", node_allow)
builder.add_node("node_block", node_block)

# Edges
builder.add_edge(START, "node_security")
builder.add_edge("node_security", "node_policy_precheck")
builder.add_conditional_edges("node_policy_precheck", conditional_after_precheck)

builder.add_edge("node_session_check", "node_router")
builder.add_conditional_edges("node_router", conditional_after_router)

builder.add_conditional_edges(
    "node_llm", conditional_after_llm,
    ["node_block", "node_detect_pii_in_response", "node_detect_hallucination",
     "node_detect_bias", "node_retrieval_verify", "node_ai_judge", "node_detect_injection_in_response"]
)

# All parallel nodes merge into evidence fusion
builder.add_edge(
    ["node_detect_pii_in_response", "node_detect_hallucination", "node_detect_bias",
     "node_retrieval_verify", "node_ai_judge", "node_detect_injection_in_response"],
    "node_evidence_fusion"
)

builder.add_conditional_edges("node_evidence_fusion", conditional_after_fusion)
builder.add_conditional_edges("node_human_review", conditional_after_human)

builder.add_edge("node_sanitize", END)
builder.add_edge("node_allow", END)
builder.add_edge("node_block", END)

app_graph = builder.compile(checkpointer=checkpointer)
