from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import os
import time
import threading
import structlog

from backend.app.rate_limit import limiter

logger = structlog.get_logger()

app = FastAPI(
    title="ControlPlane.ai",
    description="AI Governance Middleware",
    version="0.1.0",
)

# Rate limiting — no endpoint had any request throttling before this; /chat
# and /agent-action invoke an LLM + the full ML detector pipeline per call,
# so an unthrottled client can drive real cost and CPU load.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS Configuration
# allow_origins=["*"] combined with allow_credentials=True is both insecure
# (any site could call this API using the caller's cookies/auth) and
# non-functional (browsers reject a literal wildcard origin once credentials
# are allowed) — restrict to FRONTEND_URL (comma-separated for multiple
# origins) instead. FRONTEND_URL was already in .env.example but unused.
_frontend_origins = [
    o.strip() for o in os.getenv("FRONTEND_URL", "http://localhost:5173").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handler
# Never echo raw exception text to the client by default — it can leak stack
# details, file paths, or internal identifiers. Full detail always goes to
# the server log; set DEBUG_ERRORS=true (local dev only) to also return it.
_debug_errors = os.getenv("DEBUG_ERRORS", "false").lower() == "true"


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path, exc_info=True)
    content = {"detail": "Internal server error"}
    if _debug_errors:
        content["message"] = str(exc)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)

from backend.app.api.chat import router as chat_router
from backend.app.api.dashboard import router as dashboard_router
from backend.app.api.metrics import router as metrics_router
from backend.app.db.database import engine, Base

# Create DB tables if they don't already exist. Audit logs are a compliance
# record — they must survive restarts, so we never drop existing tables here.
# Set RESET_DB_ON_START=true only for local demo resets.
if os.getenv("RESET_DB_ON_START", "false").lower() == "true":
    logger.warning("RESET_DB_ON_START=true — dropping all tables (audit history will be lost).")
    Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


def _migrate_add_missing_columns():
    """
    Lightweight additive migration for SQLite: adds any model columns missing
    from the live table. create_all() only creates NEW tables, so when a
    model gains a column (e.g. cost_usd) an existing audit_logs table is left
    behind. This never drops or rewrites data — it only ALTERs in new columns.
    """
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            col_type = col.type.compile(engine.dialect)
            default_clause = ""
            if col.default is not None and col.default.is_scalar:
                val = col.default.arg
                if isinstance(val, str):
                    default_clause = f" DEFAULT '{val}'"
                elif isinstance(val, bool):
                    default_clause = f" DEFAULT {int(val)}"
                elif val is not None:
                    default_clause = f" DEFAULT {val}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}{default_clause}'
                    ))
                logger.info("migration_added_column", table=table.name, column=col.name)
            except Exception as e:
                logger.warning("migration_column_skipped", table=table.name, column=col.name, error=str(e))


_migrate_add_missing_columns()

app.include_router(chat_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1/analytics")


def _prewarm_bias_model():
    """
    Load the BART zero-shot classifier in a background thread at startup.
    Uses a threading.Event so requests NEVER wait — they always get heuristics
    until the model is ready, then switch to ML automatically.
    """
    try:
        from backend.app.workflows.graph import _load_bias_classifier_background
        _load_bias_classifier_background()
    except Exception as e:
        logger.warning(f"Bias model prewarm failed: {e}")


@app.on_event("startup")
async def startup_event():
    from backend.app.workflows.graph import init_persistent_checkpointer
    await init_persistent_checkpointer()

    logger.info("ControlPlane starting — pre-warming ML models in background...")
    # Run in daemon thread so it doesn't block server startup
    t = threading.Thread(target=_prewarm_bias_model, daemon=True)
    t.start()


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/v1/ready")
async def readiness_check():
    return {"status": "ready"}


@app.get("/api/v1/models/status")
async def model_status():
    """Shows which ML models are currently loaded."""
    from backend.app.workflows.graph import _bias_classifier
    from backend.app.security.scanner import SecurityScanner
    from backend.app.evaluation.evaluator import ResponseEvaluator
    return {
        "presidio_pii": "loaded",       # Always loaded at scanner init
        "distilbert_safety": "loaded",  # Always loaded at evaluator init
        "bart_bias": "loaded" if (_bias_classifier not in (None, "fallback")) else "loading (heuristic fallback active)",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
