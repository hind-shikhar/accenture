"""
Unit coverage for backend/app/evaluation/evidence_fusion.py decision
branches not already covered by test_round2.py: a CONTRADICTED retrieval
result, and the pii_action="BLOCK" policy branch (decision_support /
EU — GDPR-style "no PII allowed at all" policies).
"""
from backend.app.evaluation.evidence_fusion import evidence_fusion
from backend.app.policies.registry import policy_registry
from backend.app.schemas.chat import Decision, VerificationStatus

BASE_EVIDENCE = [
    {"source": "security_scan", "pii_detected": False, "prompt_injection_score": 0.0,
     "risk_level": "low", "allowed": True},
    {"source": "hallucination", "factuality_score": 0.95, "safety_score": 1.0},
    {"source": "ai_judge", "judge_confidence": 1.0, "claim_verdict": "SUPPORTED", "bias_score": 0.0},
    {"source": "session_consistency", "drift_score": 0.0, "cumulative_risk": 0.0},
]


def test_contradicted_retrieval_blocks():
    policy = policy_registry.get_policy("internal_copilot", "global")
    evidence = BASE_EVIDENCE + [{"source": "retrieval_verifier", "verification_status": "CONTRADICTED"}]

    assessment = evidence_fusion.fuse(evidence, policy)

    assert assessment.decision == Decision.BLOCK
    assert assessment.verification_status == VerificationStatus.CONTRADICTED
    assert any("contradicts" in r.lower() for r in assessment.reasons)


def test_pii_blocked_under_gdpr_style_policy():
    """decision_support has pii_action=BLOCK regardless of geography."""
    policy = policy_registry.get_policy("decision_support", "global")
    assert policy.pii_action == "BLOCK"

    evidence = BASE_EVIDENCE + [
        {"source": "security_scan", "pii_detected": True, "pii_types": ["EMAIL"],
         "prompt_injection_score": 0.0, "risk_level": "medium", "allowed": True},
    ]

    assessment = evidence_fusion.fuse(evidence, policy)

    assert assessment.decision == Decision.BLOCK
    assert any("pii" in r.lower() for r in assessment.reasons)


def test_pii_sanitized_under_lenient_policy():
    """customer_support/global defaults to SANITIZE, not BLOCK, for the same PII evidence."""
    policy = policy_registry.get_policy("customer_support", "global")
    assert policy.pii_action == "SANITIZE"

    evidence = BASE_EVIDENCE + [
        {"source": "security_scan", "pii_detected": True, "pii_types": ["EMAIL"],
         "prompt_injection_score": 0.0, "risk_level": "medium", "allowed": True},
        {"source": "response_pii", "pii_detected": True, "masked_text": "Contact me at <EMAIL_ADDRESS>"},
    ]

    assessment = evidence_fusion.fuse(evidence, policy)

    assert assessment.decision == Decision.SANITIZE
    assert assessment.sanitized_response == "Contact me at <EMAIL_ADDRESS>"
