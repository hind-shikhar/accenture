from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./controlplane.sqlite3")


def _to_async_url(url: str) -> str:
    """Swap in an async-capable driver for the same DB. sqlite -> aiosqlite
    (already a project dependency, used by the LangGraph checkpointer),
    postgresql -> asyncpg (see requirements-optional.txt). Left unchanged if
    the caller already specified an async dialect explicitly."""
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith(("postgresql://", "postgres://")) and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
            "postgres://", "postgresql+asyncpg://", 1
        )
    return url


ASYNC_DATABASE_URL = _to_async_url(DATABASE_URL)

# Sync engine: used ONLY for one-time startup schema creation/migration
# (main.py's Base.metadata.create_all / _migrate_add_missing_columns), which
# runs at import time before uvicorn's event loop exists. Every request-time
# DB access goes through the async engine below instead — every FastAPI route
# that touched a synchronous Session used to run blocking DB I/O directly on
# the asyncio event loop thread, serializing concurrent requests under load.
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in ASYNC_DATABASE_URL else {},
    # NullPool: opens a fresh DBAPI connection per checkout instead of
    # pooling one across requests/tasks. A pooled connection opened against
    # one asyncio event loop cannot be reused from another (each pytest-asyncio
    # test function gets its own loop by default; a multi-worker/reload
    # deployment can have the same issue) — NullPool trades a little
    # per-request connection overhead for never hitting that failure mode.
    poolclass=NullPool,
)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
