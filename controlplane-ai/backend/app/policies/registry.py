from typing import Dict, Any

class UseCasePolicy:
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.auto_approve_threshold: float = config.get("auto_approve_threshold", 88)
        self.review_threshold: float = config.get("review_threshold", 72)
        self.max_latency_ms: int = config.get("max_latency_ms", 3000)
        # realtime = customer-facing chat (skip the heaviest ML detector, hard timeouts);
        # standard = internal copilot (full detector suite, generous timeouts);
        # batch = decision-support / regulated (full suite, no timeout — correctness over speed).
        self.latency_tier: str = config.get("latency_tier", "standard")
        self.allow_external_models: bool = config.get("allow_external_models", True)
        self.pii_action: str = config.get("pii_action", "SANITIZE")  # SANITIZE | BLOCK | ALLOW
        self.require_hitl_below: float = config.get("require_hitl_below", 80)
        self.require_retrieval_verification: bool = config.get("require_retrieval_verification", False)
        self.require_ai_judge_above_session_risk: int = config.get("require_ai_judge_above_session_risk", 40)
        self.session_escalation_thresholds: Dict[str, int] = config.get("session_escalation_thresholds", {
            "normal": 40, "judge_required": 80, "review_forced": 120
        })
        self.block_irreversible_actions: bool = config.get("block_irreversible_actions", True)


# Base policy definitions
_POLICY_CONFIGS = {
    "customer_support": {
        "auto_approve_threshold": 90,
        "review_threshold": 75,
        "max_latency_ms": 1500,      # Real-time — strict SLA
        "latency_tier": "realtime",
        "allow_external_models": True,
        "pii_action": "SANITIZE",    # Never block, always clean
        "require_hitl_below": 78,
        "require_retrieval_verification": False,
        "require_ai_judge_above_session_risk": 30,
        "block_irreversible_actions": True,
        # High volume, low-stakes chit-chat — tolerate more turns before escalating.
        "session_escalation_thresholds": {"normal": 60, "judge_required": 100, "review_forced": 150},
    },
    "internal_copilot": {
        "auto_approve_threshold": 85,
        "review_threshold": 70,
        "max_latency_ms": 3000,
        "latency_tier": "standard",
        "allow_external_models": True,
        "pii_action": "SANITIZE",
        "require_hitl_below": 75,
        "require_retrieval_verification": True,
        "require_ai_judge_above_session_risk": 40,
        "block_irreversible_actions": True,
    },
    "decision_support": {
        "auto_approve_threshold": 92,   # Strictest — regulated workflow
        "review_threshold": 80,
        "max_latency_ms": 5000,         # Longer SLA — correctness > speed
        "latency_tier": "batch",
        "allow_external_models": False, # No external APIs for regulated data
        "pii_action": "BLOCK",          # Never allow PII in regulated context
        "require_hitl_below": 88,
        "require_retrieval_verification": True,
        "require_ai_judge_above_session_risk": 20,
        "block_irreversible_actions": True,
        # Regulated decision support — escalate to forced review much sooner.
        "session_escalation_thresholds": {"normal": 25, "judge_required": 50, "review_forced": 80},
    },
}

# Regional overrides (applied on top of base policy)
_REGIONAL_OVERRIDES = {
    "eu": {
        "pii_action": "BLOCK",   # GDPR — no PII allowed at all
        "auto_approve_threshold": 92,
    },
    "us": {
        "pii_action": "SANITIZE",  # CCPA — sanitize is acceptable
    },
    "global": {},  # No override
}


class PolicyRegistry:
    def get_policy(self, use_case: str, geography: str = "global") -> UseCasePolicy:
        base = dict(_POLICY_CONFIGS.get(use_case, _POLICY_CONFIGS["internal_copilot"]))
        overrides = _REGIONAL_OVERRIDES.get(geography, {})
        merged = {**base, **overrides}
        policy_name = f"{use_case}_{geography}"
        return UseCasePolicy(name=policy_name, config=merged)

    def update_threshold(self, use_case: str, geography: str, new_threshold: float):
        """Dynamically apply an approved auto-tuner recommendation to the registry."""
        if use_case in _POLICY_CONFIGS:
            _POLICY_CONFIGS[use_case]["require_hitl_below"] = new_threshold
            _POLICY_CONFIGS[use_case]["review_threshold"] = new_threshold
            # Ensure auto_approve is always strictly above review threshold
            if _POLICY_CONFIGS[use_case]["auto_approve_threshold"] <= new_threshold:
                _POLICY_CONFIGS[use_case]["auto_approve_threshold"] = new_threshold + 5


# Singleton
policy_registry = PolicyRegistry()
