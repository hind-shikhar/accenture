"""
Action Risk Gate — evaluates proposed AI-agent actions before tool execution.
In prototype, tool execution is SIMULATED ONLY (no irreversible real-world operations).
"""
import uuid
import time
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()

# Action risk catalog
ACTION_RISK_LEVELS: Dict[str, Dict[str, Any]] = {
    "SEND_EMAIL":          {"risk": 40,  "reversible": True,  "require_hitl": False, "category": "communication"},
    "UPDATE_RECORD":       {"risk": 55,  "reversible": True,  "require_hitl": False, "category": "data_write"},
    "DELETE_RECORD":       {"risk": 90,  "reversible": False, "require_hitl": True,  "category": "data_destroy"},
    "ISSUE_REFUND":        {"risk": 75,  "reversible": False, "require_hitl": True,  "category": "financial"},
    "EXPORT_DATA":         {"risk": 85,  "reversible": False, "require_hitl": True,  "category": "data_exfil"},
    "READ_DATA":           {"risk": 15,  "reversible": True,  "require_hitl": False, "category": "data_read"},
    "SEND_NOTIFICATION":   {"risk": 30,  "reversible": True,  "require_hitl": False, "category": "communication"},
    "GENERATE_REPORT":     {"risk": 20,  "reversible": True,  "require_hitl": False, "category": "reporting"},
    "ESCALATE_TICKET":     {"risk": 35,  "reversible": True,  "require_hitl": False, "category": "workflow"},
    "CLOSE_ACCOUNT":       {"risk": 95,  "reversible": False, "require_hitl": True,  "category": "critical"},
}

BLOCK_THRESHOLD = 80      # Risk score above this → BLOCK
REVIEW_THRESHOLD = 50     # Risk score above this → REVIEW


class ActionGate:
    def evaluate(
        self,
        action_type: str,
        use_case: str = "internal_copilot",
        session_risk: float = 0.0,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        start = time.time()
        action_id = str(uuid.uuid4())

        action_def = ACTION_RISK_LEVELS.get(action_type.upper())
        if not action_def:
            # Unknown action — treat as high risk
            action_def = {"risk": 80, "reversible": False, "require_hitl": True, "category": "unknown"}

        base_risk = action_def["risk"]

        # Amplify risk based on session state
        if session_risk >= 80:
            base_risk = min(base_risk + 20, 100)

        # Amplify risk for decision_support use case
        if use_case == "decision_support":
            base_risk = min(base_risk + 10, 100)

        reasons = []
        decision = "ALLOW"

        if not action_def["reversible"]:
            reasons.append(f"Action '{action_type}' is irreversible")

        if action_def["require_hitl"] or base_risk >= BLOCK_THRESHOLD:
            decision = "BLOCK"
            reasons.append(f"Risk score {base_risk} exceeds BLOCK threshold ({BLOCK_THRESHOLD})")
            reasons.append("Mandatory HITL approval required before execution")
        elif base_risk >= REVIEW_THRESHOLD:
            decision = "REVIEW"
            reasons.append(f"Risk score {base_risk} requires human review")

        if session_risk >= 80:
            reasons.append(f"Session cumulative risk elevated ({session_risk:.0f})")

        latency = (time.time() - start) * 1000

        result = {
            "action_id": action_id,
            "action_type": action_type,
            "risk_score": base_risk,
            "reversible": action_def["reversible"],
            "category": action_def["category"],
            "decision": decision,
            "require_hitl": action_def["require_hitl"],
            "reasons": reasons,
            "executed": False,  # Always False in prototype
            "latency_ms": round(latency, 2)
        }

        logger.info("action_gate_evaluated",
                    action=action_type,
                    risk=base_risk,
                    decision=decision)
        return result

    def simulate_execution(self, action_type: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Simulate tool execution (NEVER performs real operations)."""
        return {
            "simulated": True,
            "action": action_type,
            "status": "SIMULATION_ONLY — no real operation performed",
            "parameters_received": parameters or {}
        }


# Singleton
action_gate = ActionGate()
