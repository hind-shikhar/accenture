from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, DateTime
from sqlalchemy.sql import func
from backend.app.db.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    prompt = Column(String, nullable=True)
    response_text = Column(String)
    sanitized_response = Column(String, nullable=True)

    # Routing
    selected_model = Column(String)
    provider = Column(String)
    latency_ms = Column(Float)

    # Context
    use_case = Column(String, default="internal_copilot")
    geography = Column(String, default="global")
    session_id = Column(String, nullable=True, index=True)
    turn_number = Column(Integer, default=1)
    cumulative_session_risk = Column(Float, default=0.0)

    # Risk assessment
    security_result = Column(JSON)
    evaluation_result = Column(JSON)
    composite_risk = Column(JSON, nullable=True)
    trust_score = Column(Float)
    risk_level = Column(String)
    decision = Column(String, default="ALLOW")
    verification_status = Column(String, default="NOT_CHECKED")
    overlapping_risks = Column(JSON, nullable=True)
    primary_risk_category = Column(String, default="NONE")
    detector_latencies = Column(JSON, nullable=True)
    detector_costs = Column(JSON, nullable=True)
    cost_usd = Column(Float, default=0.0)
    latency_tier = Column(String, default="standard")
    latency_budget_ms = Column(Integer, default=0)
    latency_budget_met = Column(Boolean, default=True)

    # HITL
    human_review_required = Column(Boolean, default=False)
    human_review_status = Column(String, default="na")  # na, pending, approved, rejected, sanitized

    # Feedback
    human_override = Column(Boolean, default=False)
    human_override_decision = Column(String, nullable=True)


class ThresholdRecommendation(Base):
    __tablename__ = "threshold_recommendations"

    id = Column(String, primary_key=True, index=True)
    use_case = Column(String)
    current_threshold = Column(Float)
    recommended_threshold = Column(Float)
    reason = Column(String)
    fp_rate = Column(Float)
    sample_size = Column(Integer)
    status = Column(String, default="awaiting_admin_approval")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String, nullable=True)


class AgentActionLog(Base):
    __tablename__ = "agent_action_logs"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    session_id = Column(String, nullable=True)
    action_type = Column(String)
    target = Column(String, nullable=True)
    parameters = Column(JSON, nullable=True)
    risk_score = Column(Float)
    decision = Column(String)
    reasons = Column(JSON)
    executed = Column(Boolean, default=False)
    use_case = Column(String)
