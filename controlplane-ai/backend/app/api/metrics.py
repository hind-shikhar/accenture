from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from collections import defaultdict
import statistics

from backend.app.db.database import get_db
from backend.app.db.models import AuditLog, AgentActionLog
from backend.app.evaluation.threshold_tuner import threshold_tuner

router = APIRouter()


@router.get("/full")
async def get_full_metrics(db: Session = Depends(get_db)):
    """Comprehensive metrics endpoint for the Round 2 dashboard."""
    logs = db.query(AuditLog).all()
    agent_logs = db.query(AgentActionLog).all()

    if not logs:
        return _empty_metrics()

    latencies = [l.latency_ms for l in logs if l.latency_ms]
    trust_scores = [l.trust_score for l in logs if l.trust_score]

    # Latency percentiles
    p50 = statistics.median(latencies) if latencies else 0
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 2 else (latencies[0] if latencies else 0)

    # Decision distribution
    decisions = defaultdict(int)
    for l in logs:
        decisions[l.decision or "ALLOW"] += 1
    total = len(logs)

    # Verification status distribution
    verification = defaultdict(int)
    for l in logs:
        verification[l.verification_status or "NOT_CHECKED"] += 1

    # Risk category distribution
    risk_cats = defaultdict(int)
    for l in logs:
        risk_cats[l.primary_risk_category or "NONE"] += 1

    # Per-use-case breakdown
    use_case_stats = defaultdict(lambda: {"total": 0, "blocked": 0, "sanitized": 0, "reviewed": 0,
                                           "avg_trust": [], "latencies": [], "costs": [],
                                           "budget_met": 0, "budget_ms": 0})
    for l in logs:
        uc = l.use_case or "unknown"
        use_case_stats[uc]["total"] += 1
        use_case_stats[uc]["avg_trust"].append(l.trust_score or 0)
        use_case_stats[uc]["latencies"].append(l.latency_ms or 0)
        use_case_stats[uc]["costs"].append(l.cost_usd or 0.0)
        if l.latency_budget_met:
            use_case_stats[uc]["budget_met"] += 1
        use_case_stats[uc]["budget_ms"] = l.latency_budget_ms or use_case_stats[uc]["budget_ms"]
        if l.decision == "BLOCK":
            use_case_stats[uc]["blocked"] += 1
        elif l.decision == "SANITIZE":
            use_case_stats[uc]["sanitized"] += 1
        elif l.human_review_required:
            use_case_stats[uc]["reviewed"] += 1

    use_case_summary = {}
    for uc, stats in use_case_stats.items():
        t = stats["total"]
        lats = stats["latencies"]
        costs = stats["costs"]
        use_case_summary[uc] = {
            "total": t,
            "block_rate": round(stats["blocked"] / t, 3) if t else 0,
            "sanitize_rate": round(stats["sanitized"] / t, 3) if t else 0,
            "review_rate": round(stats["reviewed"] / t, 3) if t else 0,
            "avg_trust_score": round(sum(stats["avg_trust"]) / t, 2) if t else 0,
            "p50_latency_ms": round(statistics.median(lats), 2) if lats else 0,
            "avg_cost_usd": round(sum(costs) / t, 6) if t else 0,
            "total_cost_usd": round(sum(costs), 4),
            "latency_budget_ms": stats["budget_ms"],
            "latency_budget_compliance_rate": round(stats["budget_met"] / t, 3) if t else 1.0,
        }

    # Session escalations
    session_escalations = len(set(
        l.session_id for l in logs
        if l.cumulative_session_risk and l.cumulative_session_risk >= 80
    ))

    # Agent action stats
    agent_blocked = sum(1 for a in agent_logs if a.decision == "BLOCK")
    agent_total = len(agent_logs)

    # Detector latency averages
    detector_agg = defaultdict(list)
    for l in logs:
        if l.detector_latencies:
            for det, lat in l.detector_latencies.items():
                if lat:
                    detector_agg[det].append(lat)
    avg_detector_latency = {
        k: round(sum(v) / len(v), 2) for k, v in detector_agg.items() if v
    }

    # Human override rate
    overrides = sum(1 for l in logs if l.human_override)
    reviewed = sum(1 for l in logs if l.human_review_required)
    override_rate = round(overrides / reviewed, 3) if reviewed else 0.0

    # Threshold recommendation history
    threshold_history = threshold_tuner.list_history()

    # ── Cost & latency-budget rollups ──────────────────────────────────────
    # Illustrative unit economics (see backend/app/costs/pricing.py) applied to
    # observed traffic — makes the cost of the governance layer itself visible,
    # not just the underlying model call.
    costs = [l.cost_usd or 0.0 for l in logs]
    total_cost_usd = round(sum(costs), 4)
    avg_cost_per_request_usd = round(total_cost_usd / total, 6) if total else 0.0
    budget_met_count = sum(1 for l in logs if l.latency_budget_met)
    latency_budget_compliance_rate = round(budget_met_count / total, 3) if total else 1.0

    # Detector cost breakdown (which checks are actually the expensive ones)
    detector_cost_agg = defaultdict(list)
    for l in logs:
        if l.detector_costs:
            for det, cost in l.detector_costs.items():
                if cost:
                    detector_cost_agg[det].append(cost)
    avg_detector_cost_usd = {
        k: round(sum(v) / len(v), 6) for k, v in detector_cost_agg.items() if v
    }

    # Reference volume from the challenge brief: "tens of thousands of
    # interactions per week combined" — 40,000/week is the illustrative midpoint.
    REFERENCE_WEEKLY_VOLUME = 40_000
    projected_weekly_cost_usd = round(avg_cost_per_request_usd * REFERENCE_WEEKLY_VOLUME, 2)

    return {
        "total_requests": total,
        "p50_checker_latency_ms": round(p50, 2),
        "p95_checker_latency_ms": round(p95, 2),
        "avg_trust_score": round(sum(trust_scores) / len(trust_scores), 2) if trust_scores else 0,
        "decision_distribution": {k: round(v / total, 3) for k, v in decisions.items()},
        "verification_status_distribution": {k: round(v / total, 3) for k, v in verification.items()},
        "risk_category_distribution": {k: round(v / total, 3) for k, v in risk_cats.items()},
        "sanitize_rate": round(decisions.get("SANITIZE", 0) / total, 3),
        "block_rate": round(decisions.get("BLOCK", 0) / total, 3),
        "human_override_rate": override_rate,
        "session_escalation_count": session_escalations,
        "agent_action_block_rate": round(agent_blocked / agent_total, 3) if agent_total else 0,
        "agent_actions_total": agent_total,
        "avg_detector_latency_ms": avg_detector_latency,
        "avg_detector_cost_usd": avg_detector_cost_usd,
        "total_cost_usd": total_cost_usd,
        "avg_cost_per_request_usd": avg_cost_per_request_usd,
        "latency_budget_compliance_rate": latency_budget_compliance_rate,
        "reference_weekly_volume": REFERENCE_WEEKLY_VOLUME,
        "projected_weekly_cost_usd": projected_weekly_cost_usd,
        "per_use_case": use_case_summary,
        "threshold_recommendation_history": threshold_history[-5:],
    }


def _empty_metrics():
    return {
        "total_requests": 0,
        "p50_checker_latency_ms": 0,
        "p95_checker_latency_ms": 0,
        "avg_trust_score": 0,
        "decision_distribution": {},
        "verification_status_distribution": {},
        "risk_category_distribution": {},
        "sanitize_rate": 0, "block_rate": 0, "human_override_rate": 0,
        "session_escalation_count": 0, "agent_action_block_rate": 0,
        "agent_actions_total": 0, "avg_detector_latency_ms": {},
        "avg_detector_cost_usd": {}, "total_cost_usd": 0, "avg_cost_per_request_usd": 0,
        "latency_budget_compliance_rate": 1.0, "reference_weekly_volume": 40_000,
        "projected_weekly_cost_usd": 0,
        "per_use_case": {}, "threshold_recommendation_history": []
    }
