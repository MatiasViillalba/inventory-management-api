"""Async database session management.

This module configures two separate SQLAlchemy async engines, because
FastAPI and Celery have incompatible relationships with the event
loop: Uvicorn runs the whole app on a single event loop for the
process's lifetime, so `engine`'s pooled connections stay valid for as
long as the pool holds onto them. Celery wraps each task in its own
`asyncio.run()` call (see any module under app/tasks/), creating and
destroying a fresh event loop per task. A pooled asyncpg connection
handed back by task 1 and reused by task 2 is still bound to task 1's
now-closed event loop, and fails the moment it's touched — reliably
reproducible as `AttributeError: 'NoneType' object has no attribute
'send'` on Windows the second time any Celery task opens a session.
`task_engine` sidesteps this with `NullPool`: every checkout opens a
new connection and closes it on return, so no connection ever survives
past the event loop it was created on.

get_db is the FastAPI dependency backed by the pooled engine;
TaskSessionLocal is what every module under app/tasks/ should use
instead of get_db (Celery tasks have no FastAPI dependency injection
to receive get_db from anyway).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

task_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=NullPool,
)

TaskSessionLocal = async_sessionmaker(
    bind=task_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for use as a FastAPI dependency.

    The session is automatically closed after the request completes,
    regardless of whether it succeeded or raised an exception. Callers
    are responsible for committing or rolling back transactions
    explicitly within their own logic (typically in the service layer).

    Not safe to use from a Celery task — see the module docstring and
    use TaskSessionLocal instead.

    Yields:
        AsyncSession: An active SQLAlchemy async session bound to the
            pooled engine.
    """
    async with AsyncSessionLocal() as session:
        yield session
