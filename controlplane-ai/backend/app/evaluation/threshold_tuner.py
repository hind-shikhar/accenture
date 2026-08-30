"""
Threshold Tuner.
Analyzes FP rates from real human-review outcomes and generates
RECOMMENDATIONS only. Never auto-modifies production thresholds — admin
must explicitly approve.

Recommendations are persisted in the ThresholdRecommendation table
(backend/app/db/models.py) so they survive a server restart and are
auditable — this used to be an in-memory dict that also seeded a permanent
fake "demo-rec-123" recommendation on every process start, indistinguishable
from the API's perspective from a real one.

Feedback is not duplicated into a separate in-memory store either: AuditLog's
human_review_required / human_override / human_override_decision columns
(written by backend/app/api/dashboard.py's submit_review()) are the single
source of truth for what a human actually decided on a REVIEW-flagged
request, so compute_fp_rate reads directly from AuditLog.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db.models import AuditLog, ThresholdRecommendation as ThresholdRecDB
import structlog

logger = structlog.get_logger()


def _serialize(rec: ThresholdRecDB) -> Dict[str, Any]:
    return {
        "recommendation_id": rec.id,
        "use_case": rec.use_case,
        "current_threshold": rec.current_threshold,
        "recommended_threshold": rec.recommended_threshold,
        "reason": rec.reason,
        "fp_rate": rec.fp_rate,
        "sample_size": rec.sample_size,
        "status": rec.status,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "resolved_at": rec.resolved_at.isoformat() if rec.resolved_at else None,
        "resolved_by": rec.resolved_by,
    }


class ThresholdTuner:
    async def compute_fp_rate(self, db: AsyncSession, use_case: str, n: int = 100) -> Optional[Dict[str, Any]]:
        """Compute false positive rate for a use case from real human-review
        outcomes recorded on AuditLog, over its most recent n REVIEW-flagged rows."""
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.use_case == use_case, AuditLog.human_review_required == True)
            .order_by(AuditLog.timestamp.desc())
            .limit(n)
        )
        reviews = result.scalars().all()
        if len(reviews) < 10:
            return None  # Not enough data

        # FP: system said REVIEW, human approved anyway (over-flagging)
        fp = [r for r in reviews if r.human_override and r.human_override_decision == "approve"]
        fp_rate = len(fp) / len(reviews) if reviews else 0.0

        # FN: system said ALLOW/SANITIZE but should have flagged (under-flagging).
        # No signal for this exists without explicit downstream-incident
        # tracking (a human catching a bad response the system never
        # escalated) — left at 0.0 rather than fabricated from a proxy.
        fn_rate = 0.0

        return {
            "use_case": use_case,
            "sample_size": len(reviews),
            "review_count": len(reviews),
            "fp_count": len(fp),
            "fp_rate": round(fp_rate, 3),
            "fn_rate": round(fn_rate, 3),
        }

    async def generate_recommendation(
        self, db: AsyncSession, use_case: str, current_threshold: float
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a threshold recommendation if FP rate warrants it.
        Persists the recommendation — DOES NOT modify the live threshold.
        """
        stats = await self.compute_fp_rate(db, use_case)
        if not stats:
            return None

        fp_rate = stats["fp_rate"]
        if fp_rate > 0.30:
            # Too many false positives — lower threshold to reduce alert fatigue
            recommended = round(current_threshold - 3, 1)
            reason = f"FP rate = {fp_rate*100:.1f}% (> 30%) — threshold too strict"
        elif fp_rate < 0.05 and stats["sample_size"] >= 50:
            # Very few FPs — can safely raise threshold for stricter governance
            recommended = round(current_threshold + 2, 1)
            reason = f"FP rate = {fp_rate*100:.1f}% (< 5%) — threshold can be tightened"
        else:
            return None  # No recommendation needed

        rec = ThresholdRecDB(
            id=str(uuid.uuid4())[:8],
            use_case=use_case,
            current_threshold=current_threshold,
            recommended_threshold=recommended,
            reason=reason,
            fp_rate=fp_rate,
            sample_size=stats["sample_size"],
            status="awaiting_admin_approval",
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        logger.info("threshold_recommendation_generated", recommendation_id=rec.id, use_case=use_case,
                    fp_rate=fp_rate, recommended_threshold=recommended)
        return _serialize(rec)

    async def approve_recommendation(self, db: AsyncSession, rec_id: str, admin_id: str = "admin") -> Optional[Dict[str, Any]]:
        """Admin approves a recommendation. Caller must still update PolicyRegistry."""
        rec = await db.get(ThresholdRecDB, rec_id)
        if not rec or rec.status != "awaiting_admin_approval":
            return None
        rec.status = "approved"
        rec.resolved_at = datetime.now(timezone.utc)
        rec.resolved_by = admin_id
        await db.commit()
        await db.refresh(rec)
        logger.info("threshold_recommendation_approved", rec_id=rec_id, use_case=rec.use_case,
                    new_threshold=rec.recommended_threshold)
        return _serialize(rec)

    async def reject_recommendation(self, db: AsyncSession, rec_id: str, admin_id: str = "admin") -> Optional[Dict[str, Any]]:
        rec = await db.get(ThresholdRecDB, rec_id)
        if not rec or rec.status != "awaiting_admin_approval":
            return None
        rec.status = "rejected"
        rec.resolved_at = datetime.now(timezone.utc)
        rec.resolved_by = admin_id
        await db.commit()
        await db.refresh(rec)
        return _serialize(rec)

    async def list_pending(self, db: AsyncSession) -> List[Dict[str, Any]]:
        result = await db.execute(
            select(ThresholdRecDB).where(ThresholdRecDB.status == "awaiting_admin_approval")
        )
        return [_serialize(r) for r in result.scalars().all()]

    async def list_history(self, db: AsyncSession, limit: int = 50) -> List[Dict[str, Any]]:
        result = await db.execute(
            select(ThresholdRecDB)
            .where(ThresholdRecDB.status != "awaiting_admin_approval")
            .order_by(ThresholdRecDB.resolved_at.desc())
            .limit(limit)
        )
        return [_serialize(r) for r in result.scalars().all()]


# Singleton
threshold_tuner = ThresholdTuner()
