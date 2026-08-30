from typing import Dict, List, Optional, Any
import json
import os
import time
import structlog

logger = structlog.get_logger()

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class SessionTurn:
    def __init__(self, turn_number: int, prompt: str, response: str, risk_delta: float, timestamp: Optional[float] = None):
        self.turn_number = turn_number
        self.prompt = prompt
        self.response = response
        self.risk_delta = risk_delta
        self.timestamp = timestamp if timestamp is not None else time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_number": self.turn_number, "prompt": self.prompt, "response": self.response,
            "risk_delta": self.risk_delta, "timestamp": self.timestamp,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """Serialization for the Redis-backed store below."""
        return {
            "session_id": self.session_id,
            "use_case": self.use_case,
            "cumulative_risk": self.cumulative_risk,
            "escalation_level": self.escalation_level,
            "escalation_thresholds": self.escalation_thresholds,
            "turns": [t.to_dict() for t in self.turns],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        ctx = cls(data["session_id"], data["use_case"], data.get("escalation_thresholds"))
        ctx.cumulative_risk = data.get("cumulative_risk", 0.0)
        ctx.escalation_level = data.get("escalation_level", "normal")
        ctx.turns = [SessionTurn(**t) for t in data.get("turns", [])]
        return ctx


# How long a session survives with no new turns, when Redis-backed. Bounds
# unbounded memory/key growth for abandoned sessions instead of keeping them
# forever. Irrelevant to the in-memory fallback (which never persists past
# process exit anyway).
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24)))


class SessionStore:
    """
    Session / HITL-escalation state store.

    Backed by Redis when REDIS_URL is set and the `redis` package is
    installed (requirements-optional.txt) — required for a multi-instance
    deployment, since session state living only in one process's dict means
    a second replica, or a restart, silently resets every in-flight
    session's cumulative risk and escalation level. Falls back to the
    original in-process dict otherwise (the default/demo configuration),
    with identical behavior to before this class supported Redis at all.

    get/get_or_create/get_drift_score are async regardless of which backend
    is active, so callers don't need to know or care which one is in play.
    """

    def __init__(self):
        self._sessions: Dict[str, SessionContext] = {}
        self._redis = None
        redis_url = os.getenv("REDIS_URL")
        if redis_url and REDIS_AVAILABLE:
            try:
                self._redis = aioredis.from_url(redis_url, decode_responses=True)
                logger.info("session_store_redis_configured")
            except Exception as e:
                logger.warning("session_store_redis_init_failed", error=str(e), fallback="in-memory")
        elif redis_url and not REDIS_AVAILABLE:
            logger.warning("session_store_redis_url_set_but_package_missing",
                            detail="pip install redis — falling back to in-memory session store")

    def _redis_key(self, session_id: str) -> str:
        return f"controlplane:session:{session_id}"

    async def get_or_create(
        self,
        session_id: str,
        use_case: str = "internal_copilot",
        escalation_thresholds: Optional[Dict[str, int]] = None
    ) -> SessionContext:
        existing = await self.get(session_id)
        if existing:
            return existing
        ctx = SessionContext(session_id, use_case, escalation_thresholds)
        self._sessions[session_id] = ctx
        return ctx

    async def get(self, session_id: str) -> Optional[SessionContext]:
        if session_id in self._sessions:
            return self._sessions[session_id]
        if self._redis:
            try:
                raw = await self._redis.get(self._redis_key(session_id))
                if raw:
                    ctx = SessionContext.from_dict(json.loads(raw))
                    self._sessions[session_id] = ctx
                    return ctx
            except Exception as e:
                logger.warning("session_store_redis_read_failed", session_id=session_id, error=str(e))
        return None

    async def commit(self, session: SessionContext):
        """Persist a session mutated in place (e.g. after add_turn()). No-op
        against Redis when it isn't configured — the in-memory dict already
        holds the same object reference, so it's already current."""
        self._sessions[session.session_id] = session
        if self._redis:
            try:
                await self._redis.set(
                    self._redis_key(session.session_id),
                    json.dumps(session.to_dict()),
                    ex=SESSION_TTL_SECONDS,
                )
            except Exception as e:
                logger.warning("session_store_redis_write_failed", session_id=session.session_id, error=str(e))

    async def get_drift_score(self, session_id: str) -> float:
        """Returns how much the session risk has drifted from baseline."""
        session = await self.get(session_id)
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
