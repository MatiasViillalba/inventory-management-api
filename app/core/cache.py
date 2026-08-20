"""Async Redis client for application-level response caching.

Mirrors app/core/session.py's approach to the database engine: a
single connection pool is created once at import time and shared for
the lifetime of the process, rather than opening a new connection on
every cache read or write. The cache decorator built on top of this
client lives in a later commit.
"""

from collections.abc import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings

settings = get_settings()

redis_pool = ConnectionPool.from_url(settings.redis_url, decode_responses=True)


async def get_redis() -> AsyncGenerator[Redis, None]:
    """Yield a Redis client for use as a FastAPI dependency.

    The returned client is a thin handle bound to the shared pool, not
    a new TCP connection, so constructing and closing one per request
    is cheap; the pool itself is what's reused.

    Yields:
        Redis: An async Redis client backed by the shared connection pool.
    """
    client = Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.aclose()
