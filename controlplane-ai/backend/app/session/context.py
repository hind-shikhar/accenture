from typing import Dict, List, Optional, Any
import time
import structlog

logger = structlog.get_logger()


class SessionTurn:
    def __init__(self, turn_number: int, prompt: str, response: str, risk_delta: float):
        self.turn_number = turn_number
        self.prompt = prompt
        self.response = response
        self.risk_delta = risk_delta
        self.timestamp = time.time()


DEFAULT_ESCALATION_THRESHOLDS = {"normal": 40, "judge_required": 80, "review_forced": 120}


class SessionContext:
    def __init__(self, session_id: str, use_case: str, escalation_thresholds: Optional[Dict[str, int]] = None):
        self.session_id = session_id
        self.use_case = use_case
        self.turns: List[SessionTurn] = []
        self.cumulative_risk: float = 0.0
        # Per-policy escalation bands, e.g. a stricter decision_support policy
        # can escalate at lower cumulative risk than a lenient customer_support one.
        self.escalation_thresholds: Dict[str, int] = escalation_thresholds or DEFAULT_ESCALATION_THRESHOLDS
        self.escalation_level: str = "normal"  # normal | judge_required | review_forced
        self.action_log: List[Dict[str, Any]] = []

    def add_turn(self, prompt: str, response: str, risk_delta: float):
        turn_number = len(self.turns) + 1
        self.turns.append(SessionTurn(turn_number, prompt, response, risk_delta))
        self.cumulative_risk += risk_delta
        self._update_escalation_level()
        logger.info("session_turn_added",
                    session_id=self.session_id,
                    turn=turn_number,
                    risk_delta=risk_delta,
                    cumulative_risk=self.cumulative_risk,
                    escalation=self.escalation_level)

    def _update_escalation_level(self):
        t = self.escalation_thresholds
        if self.cumulative_risk >= t.get("review_forced", DEFAULT_ESCALATION_THRESHOLDS["review_forced"]):
            self.escalation_level = "review_forced"
        elif self.cumulative_risk >= t.get("normal", DEFAULT_ESCALATION_THRESHOLDS["normal"]):
            self.escalation_level = "judge_required"
        else:
            self.escalation_level = "normal"

    def get_history(self) -> List[Dict[str, str]]:
        return [{"turn": t.turn_number, "prompt": t.prompt[:200], "response": t.response[:200]}
                for t in self.turns[-5:]]  # Last 5 turns for context

    def log_action(self, action: Dict[str, Any]):
        self.action_log.append(action)

    @property
    def turn_count(self) -> int:
        return len(self.turns)


class SessionStore:
    """In-memory session store. In production, back with Redis."""

    def __init__(self):
        self._sessions: Dict[str, SessionContext] = {}

    def get_or_create(
        self,
        session_id: str,
        use_case: str = "internal_copilot",
        escalation_thresholds: Optional[Dict[str, int]] = None
    ) -> SessionContext:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionContext(session_id, use_case, escalation_thresholds)
        return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[SessionContext]:
        return self._sessions.get(session_id)

    def get_drift_score(self, session_id: str) -> float:
        """Returns how much the session risk has drifted from baseline."""
        session = self.get(session_id)
        if not session:
            return 0.0
        if len(session.turns) < 2:
            return 0.0
        recent_risks = [t.risk_delta for t in session.turns[-3:]]
        if len(recent_risks) > 1:
            # Only report upward drift — a session cooling off isn't a risk signal.
            return max(0.0, recent_risks[-1] - recent_risks[0])
        return 0.0


# Singleton
session_store = SessionStore()
