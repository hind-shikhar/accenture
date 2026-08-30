from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
import json, asyncio
from sqlalchemy.ext.asyncio import AsyncSession
import uuid, time, structlog

from backend.app.schemas.chat import ChatRequest, ChatResponse, Decision, VerificationStatus
from backend.app.db.database import get_db
from backend.app.db.models import AuditLog
from backend.app.workflows.graph import app_graph, ControlPlaneState, semantic_router
from backend.app.session.context import session_store
from backend.app.evaluation.action_gate import action_gate
from backend.app.db.models import AgentActionLog
from backend.app.policies.registry import policy_registry
from backend.app.rate_limit import limiter

logger = structlog.get_logger()
router = APIRouter()

# ── Streaming API (Architecture 4) ─────────────────────────────────────────────
@router.post("/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(request: Request, chat_req: ChatRequest):
    """Server-Sent Events (SSE) endpoint for real-time pipeline streaming."""
    trace_id = str(uuid.uuid4())
    initial_state = {
        "request_id": trace_id,
        "prompt": chat_req.prompt,
        "use_case": chat_req.use_case.value if chat_req.use_case else "internal_copilot",
    }
    config = {"configurable": {"thread_id": trace_id}}

    async def event_generator():
        yield f"data: {json.dumps({'status': 'Pipeline Started', 'trace_id': trace_id})}\n\n"
        try:
            async for event in app_graph.astream_events(initial_state, config=config, version="v1"):
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"]["chunk"].content
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                elif event["event"] == "on_chain_end" and event.get("name") in [
                    "node_security", "node_router", "node_evidence_fusion"
                ]:
                    yield f"data: {json.dumps({'node_completed': event['name']})}\n\n"
        except Exception as e:
            logger.error("chat_stream_failed", error=str(e), trace_id=trace_id, exc_info=True)
            yield f"data: {json.dumps({'error': 'Internal workflow error', 'trace_id': trace_id})}\n\n"
        yield "data: {\"status\": \"Pipeline Finished\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat_endpoint(request: Request, chat_req: ChatRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    start_time = time.time()
    trace_id = str(uuid.uuid4())
    session_id = chat_req.session_id or str(uuid.uuid4())

    logger.info("request_started", trace_id=trace_id, use_case=chat_req.use_case,
                geography=chat_req.geography, session=session_id)

    initial_state = {
        "request_id": trace_id,
        "prompt": chat_req.prompt,
        "cost_budget": chat_req.cost_budget,
        "sensitivity": chat_req.sensitivity,
        "use_case": chat_req.use_case.value if chat_req.use_case else "internal_copilot",
        "geography": chat_req.geography.value if chat_req.geography else "global",
        "session_id": session_id,
        "proposed_action": chat_req.proposed_action,
        "evidence": [],
        "reasons": [],
        "detector_latencies": {},
        "detector_costs": {},
        "overlapping_risks": [],
    }

    config = {"configurable": {"thread_id": trace_id}}

    try:
        final_state = await app_graph.ainvoke(initial_state, config=config)
    except Exception as e:
        logger.error("graph_execution_failed", error=str(e), trace_id=trace_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"message": "Internal workflow error", "trace_id": trace_id},
        )

    # Check if graph paused (HITL)
    current_state = await app_graph.aget_state(config)
    is_paused = len(current_state.next) > 0

    latency = (time.time() - start_time) * 1000
    decision_str = final_state.get("decision", "REVIEW" if is_paused else "ALLOW")
    final_output = final_state.get("final_output", "")
    trust_score = final_state.get("trust_score", 0.0)
    risk_level = "high" if trust_score < 70 else ("medium" if trust_score < 85 else "low")
    verification_status = final_state.get("verification_status", "NOT_CHECKED")
    overlapping_risks = final_state.get("overlapping_risks", [])
    sanitized = decision_str == "SANITIZE"

    # Cost & latency-budget accounting
    detector_costs = final_state.get("detector_costs", {})
    detector_latencies = final_state.get("detector_latencies", {})
    cost_usd = round(sum(detector_costs.values()), 6)
    policy = policy_registry.get_policy(initial_state["use_case"], initial_state["geography"])
    latency_budget_met = latency <= policy.max_latency_ms

    # Feed this request's real LLM cost/latency back into the router so
    # future estimated_cost/estimated_latency for this model tier reflect
    # actual observed traffic instead of the static catalog in router.py.
    selected_model = final_state.get("selected_model")
    if selected_model:
        semantic_router.record_observed_stats(
            selected_model, detector_costs.get("llm"), detector_latencies.get("llm")
        )

    # Update session
    security_res = final_state.get("security_result", {})
    injection_score = security_res.get("prompt_injection_score", 0.0)
    risk_delta = (100 - trust_score) * 0.5 + injection_score * 30
    use_case_str = initial_state["use_case"]

    session = await session_store.get_or_create(session_id, use_case_str)
    session.add_turn(chat_req.prompt, final_output or "", risk_delta)
    await session_store.commit(session)

    # Extract evaluation result from evidence for the frontend dashboard
    evidence_list = final_state.get("evidence", [])
    eval_result = {}
    for ev in evidence_list:
        if ev.get("source") == "hallucination":
            eval_result = {
                "factuality_score": ev.get("factuality_score", 1.0),
                "safety_score": ev.get("safety_score", 1.0)
            }
            break

    # Audit log (background)
    # Stores the Presidio-masked prompt, not the raw one — the audit trail is
    # itself a compliance-sensitive store, so it shouldn't hold the exact PII
    # the pipeline just redacted from reaching the LLM (see threat-model.md §7).
    masked_prompt_for_audit = final_state.get("masked_prompt", chat_req.prompt)

    async def log_audit():
        log_entry = AuditLog(
            id=trace_id,
            prompt=masked_prompt_for_audit,
            response_text=final_output,
            sanitized_response=final_state.get("sanitized_response"),
            selected_model=final_state.get("selected_model", "none"),
            provider=final_state.get("selected_provider", "none"),
            latency_ms=latency,
            use_case=use_case_str,
            geography=initial_state["geography"],
            session_id=session_id,
            turn_number=session.turn_count,
            cumulative_session_risk=session.cumulative_risk,
            security_result=security_res,
            evaluation_result=eval_result,
            composite_risk={"overlapping_risks": overlapping_risks,
                            "primary_risk": final_state.get("primary_risk_category", "NONE"),
                            "risk_vectors": final_state.get("risk_vectors", {})},
            trust_score=trust_score,
            risk_level=risk_level,
            decision=decision_str,
            verification_status=verification_status,
            overlapping_risks=overlapping_risks,
            primary_risk_category=final_state.get("primary_risk_category", "NONE"),
            detector_latencies=final_state.get("detector_latencies", {}),
            detector_costs=detector_costs,
            cost_usd=cost_usd,
            latency_tier=policy.latency_tier,
            latency_budget_ms=policy.max_latency_ms,
            latency_budget_met=latency_budget_met,
            human_review_required=is_paused,
            human_review_status="pending" if is_paused else ("blocked" if decision_str == "BLOCK" else "na")
        )
        db.add(log_entry)
        await db.commit()

    is_blocked = decision_str == "BLOCK" and not is_paused
    if is_blocked:
        # A raised HTTPException never returns a Response from this endpoint,
        # so a task queued via BackgroundTasks (which only runs after a
        # successful return) would silently never fire — blocked requests are
        # exactly the ones a compliance audit trail can't afford to lose, so
        # write before raising instead of deferring. Awaited directly (not a
        # blocking sync call) so this doesn't stall the event loop either.
        await log_audit()
    else:
        background_tasks.add_task(log_audit)

    logger.info("request_completed", trace_id=trace_id, decision=decision_str,
                trust_score=trust_score, latency_ms=latency)

    if is_blocked:
        raise HTTPException(status_code=403, detail={
            "message": final_output or "Blocked by policy",
            "trace_id": trace_id,
            "reasons": final_state.get("reasons", []),
            "decision": "BLOCK"
        })

    display_text = final_output
    if is_paused:
        display_text = "Your request has been queued for human review."

    return ChatResponse(
        text=display_text,
        model=final_state.get("selected_model", "none"),
        provider=final_state.get("selected_provider", "none"),
        trust_score=trust_score,
        risk_level=risk_level,
        decision=Decision(decision_str) if decision_str in Decision._value2member_map_ else Decision.REVIEW,
        verification_status=VerificationStatus(verification_status) if verification_status in VerificationStatus._value2member_map_ else VerificationStatus.NOT_CHECKED,
        overlapping_risks=overlapping_risks,
        security=security_res,
        evaluation=eval_result,
        trace_id=trace_id,
        session_id=session_id,
        sanitized=sanitized,
        cost_usd=cost_usd,
        latency_ms=round(latency, 2),
        latency_tier=policy.latency_tier,
        latency_budget_ms=policy.max_latency_ms,
        latency_budget_met=latency_budget_met
    )


@router.post("/agent-action")
@limiter.limit("30/minute")
async def evaluate_agent_action(request: Request, payload: dict, db: AsyncSession = Depends(get_db)):
    """Evaluate a proposed agent action through the Action Risk Gate."""
    action_type = payload.get("action_type", "")
    use_case = payload.get("use_case", "internal_copilot")
    session_id = payload.get("session_id")
    parameters = payload.get("parameters", {})

    session_risk = 0.0
    if session_id:
        session = await session_store.get(session_id)
        if session:
            session_risk = session.cumulative_risk

    result = action_gate.evaluate(action_type, use_case, session_risk, parameters)

    log = AgentActionLog(
        id=str(uuid.uuid4()),
        session_id=session_id,
        action_type=action_type,
        target=parameters.get("target"),
        parameters=parameters,
        risk_score=result["risk_score"],
        decision=result["decision"],
        reasons=result["reasons"],
        executed=False,
        use_case=use_case
    )
    db.add(log)
    await db.commit()

    if result["decision"] == "BLOCK":
        return {**result, "message": "Action BLOCKED by ControlPlane Action Gate. HITL required."}

    return result
