"""
Evidence Fusion Engine.
Aggregates outputs from all parallel detectors into a single CompositeRiskAssessment.
AI-as-Judge is ONE evidence source, not ground truth.
verification_status = VERIFIED requires BOTH retrieval match AND AI-Judge support.
"""
from typing import Dict, Any, List
from backend.app.schemas.chat import (
    CompositeRiskAssessment, Decision, VerificationStatus
)
from backend.app.policies.registry import UseCasePolicy
import structlog

logger = structlog.get_logger()

# Weights for evidence fusion
EVIDENCE_WEIGHTS = {
    "pii":           0.25,
    "injection":     0.25,
    "hallucination": 0.20,
    "bias":          0.10,
    "retrieval":     0.10,
    "ai_judge":      0.05,
    "session":       0.05,
}


class EvidenceFusion:
    def fuse(
        self,
        evidence_list: List[Dict[str, Any]],
        policy: UseCasePolicy,
        session_escalation: str = "normal"
    ) -> CompositeRiskAssessment:
        """
        Fuse all parallel detector evidence into a CompositeRiskAssessment.
        """
        # Build evidence lookup by source
        evidence_map: Dict[str, Dict] = {}
        for ev in evidence_list:
            evidence_map[ev.get("source", "unknown")] = ev

        # --- Extract individual risk vectors ---
        input_pii_ev = evidence_map.get("security_scan", {})
        response_pii_ev = evidence_map.get("response_pii", {})
        retrieval_ev = evidence_map.get("retrieval_verifier", {})
        judge_ev = evidence_map.get("ai_judge", {})
        session_ev = evidence_map.get("session_consistency", {})
        hallucination_ev = evidence_map.get("hallucination", {})
        bias_ev = evidence_map.get("bias", {})
        injection_ev = evidence_map.get("injection", {})

        # PII risk should trigger if detected in EITHER input or output
        pii_detected = input_pii_ev.get("pii_detected") or response_pii_ev.get("pii_detected")
        pii_risk = 1.0 if pii_detected else 0.0
        
        # We need the most relevant masked text for sanitization
        # The prompt is masked BEFORE the LLM, so the LLM output is inherently safe from input PII.
        # We only need to sanitize the final output if the LLM generated NEW PII.
        sanitized_llm_response = response_pii_ev.get("masked_text")

        injection_risk = input_pii_ev.get("prompt_injection_score", injection_ev.get("injection_score", 0.0))
        hallucination_risk = 1.0 - hallucination_ev.get("factuality_score", 1.0)
        # max(), not judge_ev.get(key, fallback) — the AI-Judge's evidence
        # ALWAYS includes a "bias_score" key, even when it's skipped for a
        # fresh session (bias_score hardcoded to 0.0, see node_ai_judge in
        # workflows/graph.py). A .get(key, fallback) only uses the fallback
        # when the key is entirely ABSENT, so that fallback to the dedicated
        # bias detector's real score was unreachable — node_detect_bias's
        # BART/heuristic finding was silently discarded whenever the judge
        # ran (or was skipped), regardless of what it found. Same
        # defense-in-depth fusion convention as _ml_injection_score elsewhere
        # in this pipeline: neither detector is trusted as the sole signal.
        bias_risk = max(judge_ev.get("bias_score", 0.0), bias_ev.get("bias_score", 0.0))
        retrieval_risk = 0.5 if retrieval_ev.get("verification_status") == "UNVERIFIED" else (
            0.9 if retrieval_ev.get("verification_status") == "CONTRADICTED" else 0.0
        )
        judge_risk = 1.0 - judge_ev.get("judge_confidence", 1.0)
        session_drift = session_ev.get("drift_score", 0.0)
        session_risk = min(session_drift / 100.0, 1.0)

        risk_vectors = {
            "pii": round(pii_risk, 3),
            "injection": round(injection_risk, 3),
            "hallucination": round(hallucination_risk, 3),
            "bias": round(bias_risk, 3),
            "retrieval": round(retrieval_risk, 3),
            "ai_judge": round(judge_risk, 3),
            "session": round(session_risk, 3),
        }

        # Weighted composite risk
        composite_risk = sum(
            risk_vectors.get(k, 0.0) * EVIDENCE_WEIGHTS.get(k, 0.0)
            for k in EVIDENCE_WEIGHTS
        )
        trust_score = round((1.0 - composite_risk) * 100, 2)

        # --- Determine primary and overlapping risks ---
        active_risks = {k: v for k, v in risk_vectors.items() if v > 0.3}
        sorted_risks = sorted(active_risks.items(), key=lambda x: x[1], reverse=True)

        primary_risk_category = "NONE"
        overlapping_risks = []

        risk_category_map = {
            "pii": "PRIVACY",
            "injection": "ADVERSARIAL",
            "hallucination": "HALLUCINATION",
            "bias": "BIAS",
            "retrieval": "HALLUCINATION",
            "ai_judge": "HALLUCINATION",
            "session": "ADVERSARIAL",
        }

        if sorted_risks:
            primary_risk_category = risk_category_map.get(sorted_risks[0][0], "NONE")
            unique_categories = list(dict.fromkeys(
                risk_category_map.get(r[0], "NONE") for r in sorted_risks
            ))
            if len(unique_categories) > 1:
                overlapping_risks = unique_categories

        # --- Determine verification status ---
        retrieval_status = retrieval_ev.get("verification_status", "NOT_CHECKED")
        judge_verdict = judge_ev.get("claim_verdict", "SUPPORTED")

        # VERIFIED requires BOTH retrieval match AND AI-Judge support
        if retrieval_status == "VERIFIED" and judge_verdict == "SUPPORTED":
            verification_status = VerificationStatus.VERIFIED
        elif retrieval_status == "CONTRADICTED":
            verification_status = VerificationStatus.CONTRADICTED
        elif retrieval_status == "PARTIALLY_VERIFIED" or (
                retrieval_status == "VERIFIED" and judge_verdict == "UNCERTAIN"):
            verification_status = VerificationStatus.PARTIALLY_VERIFIED
        elif retrieval_status == "NOT_CHECKED":
            verification_status = VerificationStatus.NOT_CHECKED
        else:
            verification_status = VerificationStatus.UNVERIFIED

        # --- Session escalation override ---
        if session_escalation == "review_forced":
            trust_score = min(trust_score, policy.review_threshold - 1)

        # --- Decision logic ---
        reasons = []
        sanitized_response = None
        decision = Decision.ALLOW

        # Check injection first (always BLOCK)
        if injection_risk >= 0.7:
            decision = Decision.BLOCK
            reasons.append("Prompt injection detected")

        # Check PII action based on policy
        elif pii_detected:
            pii_action = policy.pii_action
            if pii_action == "BLOCK":
                decision = Decision.BLOCK
                reasons.append(f"PII detected — policy ({policy.name}) mandates BLOCK")
            elif pii_action == "SANITIZE":
                decision = Decision.SANITIZE
                reasons.append(f"PII detected — policy ({policy.name}) mandates SANITIZE")
                sanitized_response = sanitized_llm_response

        # Check contradicted retrieval
        if decision == Decision.ALLOW and verification_status == VerificationStatus.CONTRADICTED:
            decision = Decision.BLOCK
            reasons.append("Response contradicts verified source documents")

        # Check trust score thresholds
        if decision == Decision.ALLOW:
            if trust_score < policy.review_threshold:
                decision = Decision.REVIEW
                reasons.append(f"Trust score {trust_score} below review threshold ({policy.review_threshold})")
            elif trust_score < policy.auto_approve_threshold:
                if verification_status == VerificationStatus.UNVERIFIED and policy.require_retrieval_verification:
                    decision = Decision.REVIEW
                    reasons.append("Verification required but claims are UNVERIFIED")
                elif hallucination_risk > 0.2:
                    decision = Decision.REVIEW
                    reasons.append(f"Hallucination risk elevated ({hallucination_risk:.2f})")

        human_review_required = decision == Decision.REVIEW

        assessment = CompositeRiskAssessment(
            trust_score=trust_score,
            primary_risk_category=primary_risk_category,
            overlapping_risks=overlapping_risks,
            risk_vectors=risk_vectors,
            evidence=evidence_list,
            verification_status=verification_status,
            decision=decision,
            reasons=reasons,
            policy_name=policy.name,
            human_review_required=human_review_required,
            sanitized_response=sanitized_response
        )

        logger.info("evidence_fused",
                    trust_score=trust_score,
                    decision=decision.value,
                    primary_risk=primary_risk_category,
                    overlapping=overlapping_risks,
                    verification=verification_status.value)

        return assessment


# Singleton
evidence_fusion = EvidenceFusion()
