"""Async Redis client and response-caching decorator.

The client setup mirrors app/core/session.py's approach to the
database engine: a single connection pool is created once at import
time and shared for the lifetime of the process, rather than opening a
new connection on every cache read or write.

cache_response is a small cache-aside decorator for expensive,
read-only async endpoints (e.g. the aggregate report queries in
app/services/report.py): it serves a cached JSON payload when present
and falls through to the wrapped function — populating the cache on
the way out — when it isn't.
"""

import functools
import hashlib
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

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


# Dependency parameter names never included in the cache key: they're
# injected objects (a session, a client, an authenticated user), not
# part of what makes one call's *result* differ from another's.
_EXCLUDED_KWARGS = {"db", "redis", "current_user"}

AsyncEndpoint = TypeVar("AsyncEndpoint", bound=Callable[..., Awaitable[Any]])


def cache_response(
    *, key_prefix: str, ttl_seconds: int
) -> Callable[[AsyncEndpoint], AsyncEndpoint]:
    """Cache an async function's return value in Redis (cache-aside).

    The decorated function must return a Pydantic BaseModel, since
    caching relies on its model_dump_json/model_validate_json round
    trip to serialize and restore the value. If it also accepts a
    `redis: Redis` argument (as route handlers using
    `Depends(get_redis)` do), that client is used to read and write
    the cache; a Redis connection error is logged and treated as a
    cache miss rather than failing the request, since a cache outage
    must not take the underlying endpoint down with it.

    Args:
        key_prefix: A short, stable name identifying this cached
            operation, prefixed to every key it generates.
        ttl_seconds: How long a cached value stays valid.

    Returns:
        A decorator that wraps an async callable with Redis caching.
    """

    def decorator(func: AsyncEndpoint) -> AsyncEndpoint:
        return_type = func.__annotations__.get("return")
        if not (isinstance(return_type, type) and issubclass(return_type, BaseModel)):
            raise TypeError(
                f"cache_response requires an annotated BaseModel return type on "
                f"'{func.__qualname__}'."
            )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            redis = kwargs.get("redis")
            if redis is None:
                return await func(*args, **kwargs)

            cache_key = _build_cache_key(key_prefix, kwargs)

            try:
                cached = await redis.get(cache_key)
            except RedisError:
                logger.warning("Redis unavailable for cache read of '%s'.", cache_key)
                return await func(*args, **kwargs)

            if cached is not None:
                return return_type.model_validate_json(cached)

            result = await func(*args, **kwargs)

            try:
                await redis.set(cache_key, result.model_dump_json(), ex=ttl_seconds)
            except RedisError:
                logger.warning("Redis unavailable for cache write of '%s'.", cache_key)

            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def _build_cache_key(prefix: str, kwargs: dict[str, Any]) -> str:
    """Derive a stable Redis key from a prefix and the call's arguments.

    Args:
        prefix: The cache key prefix identifying the operation.
        kwargs: Keyword arguments passed to the decorated function.
            Injected dependencies (see _EXCLUDED_KWARGS) are stripped
            before hashing, since they don't affect the result.

    Returns:
        A cache key unique to this prefix and argument combination.
    """
    relevant = {
        key: value for key, value in kwargs.items() if key not in _EXCLUDED_KWARGS
    }
    if not relevant:
        return f"cache:{prefix}"

    serialized = json.dumps(relevant, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"cache:{prefix}:{digest}"
