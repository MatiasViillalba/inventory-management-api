"""Async database session management.

This module configures the SQLAlchemy async engine and provides a
FastAPI dependency (get_db) that yields a database session per request,
ensuring sessions are properly closed after each request completes,
even if an exception is raised.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for use as a FastAPI dependency.

    The session is automatically closed after the request completes,
    regardless of whether it succeeded or raised an exception. Callers
    are responsible for committing or rolling back transactions
    explicitly within their own logic (typically in the service layer).

    Yields:
        AsyncSession: An active SQLAlchemy async session bound to the
            configured engine.
    """
    async with AsyncSessionLocal() as session:
        yield session
