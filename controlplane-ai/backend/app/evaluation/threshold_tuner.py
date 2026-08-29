"""
Threshold Tuner.
Analyzes FP/FN rates from feedback and generates RECOMMENDATIONS only.
Never auto-modifies production thresholds — admin must explicitly approve.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict
import structlog

logger = structlog.get_logger()

# In-memory feedback store (in production: query AuditLog DB)
class FeedbackStore:
    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(self, use_case: str, auto_decision: str, human_decision: str):
        self._records.append({
            "use_case": use_case,
            "auto_decision": auto_decision,
            "human_decision": human_decision,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def get_recent(self, use_case: str, n: int = 100) -> List[Dict]:
        filtered = [r for r in self._records if r["use_case"] == use_case]
        return filtered[-n:]


class ThresholdTuner:
    def __init__(self):
        self._feedback = FeedbackStore()
        self._pending_recommendations: Dict[str, Dict[str, Any]] = {}
        self._applied_history: List[Dict[str, Any]] = []
        
        # Seed a demo recommendation so the UI feature is visible
        import uuid
        from datetime import datetime, timezone
        rec_id = "demo-rec-123"
        self._pending_recommendations[rec_id] = {
            "recommendation_id": rec_id,
            "use_case": "decision_support",
            "current_threshold": 80.0,
            "recommended_threshold": 76.0,
            "reason": "FP rate = 38.5% (> 30%) — threshold too strict causing alert fatigue",
            "fp_rate": 0.385,
            "sample_size": 114,
            "status": "awaiting_admin_approval",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

    def record_feedback(self, use_case: str, auto_decision: str, human_decision: str):
        """Record a human override decision for future analysis."""
        self._feedback.record(use_case, auto_decision, human_decision)

    def compute_fp_rate(self, use_case: str, n: int = 100) -> Optional[Dict[str, Any]]:
        """Compute false positive rate for a use case over last n decisions."""
        records = self._feedback.get_recent(use_case, n)
        if len(records) < 10:
            return None  # Not enough data

        # FP: system said REVIEW, human said ALLOW (over-flagging)
        reviews = [r for r in records if r["auto_decision"] == "REVIEW"]
        fp = [r for r in reviews if r["human_decision"] in ("approve", "ALLOW")]
        fp_rate = len(fp) / len(reviews) if reviews else 0.0

        # FN: system said ALLOW, human would have flagged (under-flagging)
        # We approximate this as cases where human explicitly escalated
        fn_rate = 0.0  # Requires explicit escalation tracking

        return {
            "use_case": use_case,
            "sample_size": len(records),
            "review_count": len(reviews),
            "fp_count": len(fp),
            "fp_rate": round(fp_rate, 3),
            "fn_rate": round(fn_rate, 3),
        }

    def generate_recommendation(
        self,
        use_case: str,
        current_threshold: float
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a threshold recommendation if FP rate warrants it.
        Returns a recommendation dict — DOES NOT modify the threshold.
        """
        stats = self.compute_fp_rate(use_case)
        if not stats:
            return None

        fp_rate = stats["fp_rate"]
        recommended = current_threshold

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

        rec_id = str(uuid.uuid4())[:8]
        recommendation = {
            "recommendation_id": rec_id,
            "use_case": use_case,
            "current_threshold": current_threshold,
            "recommended_threshold": recommended,
            "reason": reason,
            "fp_rate": fp_rate,
            "sample_size": stats["sample_size"],
            "status": "awaiting_admin_approval",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        self._pending_recommendations[rec_id] = recommendation
        logger.info("threshold_recommendation_generated", **{k: v for k, v in recommendation.items()
                                                             if k != "created_at"})
        return recommendation

    def approve_recommendation(self, rec_id: str, admin_id: str = "admin") -> Optional[Dict[str, Any]]:
        """
        Admin approves a recommendation.
        Returns the approved recommendation — caller must update PolicyRegistry.
        """
        rec = self._pending_recommendations.get(rec_id)
        if not rec:
            return None
        rec["status"] = "approved"
        rec["resolved_at"] = datetime.now(timezone.utc).isoformat()
        rec["resolved_by"] = admin_id
        self._applied_history.append(rec)
        del self._pending_recommendations[rec_id]
        logger.info("threshold_recommendation_approved", rec_id=rec_id, use_case=rec["use_case"],
                    new_threshold=rec["recommended_threshold"])
        return rec

    def reject_recommendation(self, rec_id: str, admin_id: str = "admin") -> Optional[Dict[str, Any]]:
        rec = self._pending_recommendations.get(rec_id)
        if not rec:
            return None
        rec["status"] = "rejected"
        rec["resolved_at"] = datetime.now(timezone.utc).isoformat()
        rec["resolved_by"] = admin_id
        self._applied_history.append(rec)
        del self._pending_recommendations[rec_id]
        return rec

    def list_pending(self) -> List[Dict[str, Any]]:
        return list(self._pending_recommendations.values())

    def list_history(self) -> List[Dict[str, Any]]:
        return self._applied_history


# Singleton
threshold_tuner = ThresholdTuner()
