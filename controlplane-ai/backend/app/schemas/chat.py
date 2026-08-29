from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class Decision(str, Enum):
    ALLOW = "ALLOW"
    SANITIZE = "SANITIZE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"

class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    NOT_CHECKED = "NOT_CHECKED"

class UseCase(str, Enum):
    CUSTOMER_SUPPORT = "customer_support"
    INTERNAL_COPILOT = "internal_copilot"
    DECISION_SUPPORT = "decision_support"

class Geography(str, Enum):
    EU = "eu"
    US = "us"
    GLOBAL = "global"

class ChatRequest(BaseModel):
    prompt: str = Field(..., max_length=4000, description="The prompt text. Limited to 4000 chars to prevent NLP engine DoS.")
    task_type: Optional[str] = "general"
    sensitivity: Optional[str] = "low"
    latency_budget_ms: Optional[int] = 3000
    cost_budget: Optional[float] = 0.01
    policy: Optional[str] = "enterprise_default"
    use_case: Optional[UseCase] = UseCase.INTERNAL_COPILOT
    geography: Optional[Geography] = Geography.GLOBAL
    session_id: Optional[str] = None
    proposed_action: Optional[str] = None  # For agentic scenarios

class SecurityResult(BaseModel):
    allowed: bool
    risk_level: str
    pii_detected: bool
    pii_types: List[str] = []
    prompt_injection_score: float = 0.0
    actions: List[str] = []

class EvaluationResult(BaseModel):
    factuality_score: float = 1.0
    safety_score: float = 1.0
    schema_compliance_score: float = 1.0
    details: Dict[str, Any] = {}

class CompositeRiskAssessment(BaseModel):
    trust_score: float
    primary_risk_category: str  # "BIAS" | "HALLUCINATION" | "PRIVACY" | "ADVERSARIAL" | "NONE"
    overlapping_risks: List[str] = []
    risk_vectors: Dict[str, float] = {}
    evidence: List[Dict[str, Any]] = []
    verification_status: VerificationStatus = VerificationStatus.NOT_CHECKED
    decision: Decision
    reasons: List[str] = []
    policy_name: str = ""
    human_review_required: bool = False
    sanitized_response: Optional[str] = None

class RouteResult(BaseModel):
    selected_model: str
    provider: str
    reason: str
    estimated_cost: float
    estimated_latency: float

class ChatResponse(BaseModel):
    text: str
    model: str
    provider: str
    trust_score: float
    risk_level: str
    decision: Decision = Decision.ALLOW
    verification_status: VerificationStatus = VerificationStatus.NOT_CHECKED
    overlapping_risks: List[str] = []
    security: Any  # SecurityResult or dict
    evaluation: Any  # EvaluationResult or dict
    trace_id: str
    session_id: Optional[str] = None
    sanitized: bool = False
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    latency_tier: str = "standard"
    latency_budget_ms: int = 0
    latency_budget_met: bool = True

class ThresholdRecommendation(BaseModel):
    recommendation_id: str
    use_case: str
    current_threshold: float
    recommended_threshold: float
    reason: str
    fp_rate: float
    sample_size: int
    status: str  # awaiting_admin_approval | approved | rejected
    created_at: str

class AgentActionRequest(BaseModel):
    action_type: str
    target: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = {}
    session_id: Optional[str] = None
    use_case: Optional[UseCase] = UseCase.INTERNAL_COPILOT
