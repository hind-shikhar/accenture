from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from typing import List, Optional
import uuid, csv, io
from datetime import datetime, timezone

from backend.app.db.database import get_db
from backend.app.db.models import AuditLog, ThresholdRecommendation as ThresholdRecDB
from backend.app.workflows.graph import app_graph
from backend.app.evaluation.threshold_tuner import threshold_tuner
from backend.app.evaluation.action_gate import action_gate
from backend.app.policies.registry import policy_registry
from langgraph.types import Command

router = APIRouter()


@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(AuditLog.id)))).scalar() or 0
    escalated = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.human_review_required == True)
    )).scalar() or 0
    avg_trust = (await db.execute(select(func.avg(AuditLog.trust_score)))).scalar() or 0.0
    sanitized = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.decision == "SANITIZE")
    )).scalar() or 0
    blocked = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.decision == "BLOCK")
    )).scalar() or 0
    allowed = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.decision == "ALLOW")
    )).scalar() or 0

    # Compute FP rate (human approved what system escalated)
    overrides = (await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.human_review_required == True,
            AuditLog.human_override == True,
            AuditLog.human_override_decision == "approve"
        )
    )).scalar() or 0
    fp_rate = round(overrides / escalated, 3) if escalated > 0 else 0.0

    return {
        "total_requests": total,
        "escalated_requests": escalated,
        "approved_responses": allowed,
        "sanitized_responses": sanitized,
        "blocked_responses": blocked,
        "average_trust_score": round(float(avg_trust), 2),
        "human_override_rate": fp_rate,
        "decision_distribution": {
            "ALLOW": allowed / total if total else 0,
            "SANITIZE": sanitized / total if total else 0,
            "REVIEW": escalated / total if total else 0,
            "BLOCK": blocked / total if total else 0,
        }
    }


from fastapi import APIRouter, Depends, HTTPException, Header

# ── RBAC Middleware (Architecture 5) ──────────────────────────────────────────
# Default to the least-privileged role when no header is sent, so a caller
# must explicitly identify as Reviewer/Admin rather than getting Admin for free.
def require_reviewer(x_user_role: str = Header("Viewer")):
    if x_user_role not in ["Admin", "Reviewer"]:
        raise HTTPException(status_code=403, detail="RBAC: Only Reviewers or Admins can perform this action.")
    return x_user_role

def require_admin(x_user_role: str = Header("Viewer")):
    if x_user_role != "Admin":
        raise HTTPException(status_code=403, detail="RBAC: Only Admins can modify policy thresholds.")
    return x_user_role
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reviews")
async def get_pending_reviews(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuditLog).where(AuditLog.human_review_status == "pending"))
    return result.scalars().all()


@router.post("/review/{log_id}")
async def submit_review(
    log_id: str,
    action: str,
    edited_text: str = None,
    db: AsyncSession = Depends(get_db),
    role: str = Depends(require_reviewer)
):
    log = (await db.execute(select(AuditLog).where(AuditLog.id == log_id))).scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Review not found")

    if log.human_review_status != "pending":
        raise HTTPException(status_code=400, detail="This request has already been reviewed by another admin.")

    valid_actions = ["approve", "reject", "edit", "regenerate", "approved", "rejected"]
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail="Invalid action")

    if action == "edit" and not edited_text:
        raise HTTPException(status_code=400, detail="Edited text cannot be empty.")

    if action == "approved": action = "approve"
    if action == "rejected": action = "reject"

    config = {"configurable": {"thread_id": log_id}}
    state = await app_graph.aget_state(config)

    if state.next:
        resume_payload = {"action": action, "text": edited_text}
        await app_graph.ainvoke(Command(resume=resume_payload), config=config)

    # This AuditLog row (human_review_required / human_override /
    # human_override_decision) IS the feedback record the threshold tuner
    # reads from (see evaluation/threshold_tuner.py's compute_fp_rate) — no
    # separate in-memory feedback store to keep in sync.
    human_outcome = "approve" if action in ("approve", "edit") else "reject"

    log.human_review_status = action if action in ("approve", "reject") else "resolved"
    log.human_override = True
    log.human_override_decision = human_outcome
    await db.commit()

    return {"status": "success", "action": action, "log_id": log_id}


@router.get("/audit")
async def get_audit_logs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(50))
    return result.scalars().all()


@router.get("/audit/export")
async def export_audit_csv(db: AsyncSession = Depends(get_db)):
    """Download all audit logs as a CSV file."""
    result = await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()))
    logs = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "timestamp", "use_case", "geography", "decision",
        "trust_score", "risk_level", "primary_risk_category",
        "verification_status", "pii_detected", "prompt_injection_score",
        "latency_ms", "model", "prompt_preview"
    ])
    for log in logs:
        sec = log.security_result or {}
        writer.writerow([
            log.id,
            log.timestamp.isoformat() if log.timestamp else "",
            log.use_case,
            log.geography,
            log.decision,
            log.trust_score,
            log.risk_level,
            log.primary_risk_category,
            log.verification_status,
            sec.get("pii_detected", False),
            sec.get("prompt_injection_score", 0.0),
            log.latency_ms,
            log.selected_model,
            (log.prompt or "")[:80],
        ])

    output.seek(0)
    filename = f"controlplane_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── Threshold Recommendations ───────────────────────────────────────────────

@router.get("/thresholds/recommendations")
async def list_recommendations(db: AsyncSession = Depends(get_db)):
    return await threshold_tuner.list_pending(db)


@router.get("/thresholds/history")
async def recommendation_history(db: AsyncSession = Depends(get_db)):
    return await threshold_tuner.list_history(db)


@router.post("/thresholds/{rec_id}/approve")
async def approve_recommendation(rec_id: str, db: AsyncSession = Depends(get_db), role: str = Depends(require_admin)):
    rec = await threshold_tuner.approve_recommendation(db, rec_id, admin_id=role)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found or already resolved")

    # Update the actual policy threshold dynamically so future prompts use it
    policy_registry.update_threshold(rec["use_case"], "global", rec["recommended_threshold"])

    return {"status": "approved", "recommendation": rec}


@router.post("/thresholds/{rec_id}/reject")
async def reject_recommendation(rec_id: str, db: AsyncSession = Depends(get_db), role: str = Depends(require_admin)):
    rec = await threshold_tuner.reject_recommendation(db, rec_id, admin_id=role)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found or already resolved")
    return {"status": "rejected", "recommendation": rec}


@router.post("/thresholds/analyze/{use_case}")
async def analyze_thresholds(use_case: str, db: AsyncSession = Depends(get_db)):
    """Trigger FP/FN analysis and generate recommendation if warranted."""
    policy = policy_registry.get_policy(use_case)
    rec = await threshold_tuner.generate_recommendation(db, use_case, policy.review_threshold)
    if not rec:
        return {"message": "No recommendation needed — FP/FN rates are within acceptable range."}
    return rec
