"""Redis pub/sub fan-out for WebSocket broadcasts across processes.

ConnectionManager only knows about WebSocket connections accepted by
its own process (see its docstring), so a broadcast triggered in one
API worker never reaches a client connected to a different worker —
inescapable once the app runs as more than a single process (e.g.
`uvicorn --workers 4`, or multiple containers behind a load balancer).

RedisBroadcaster closes that gap: instead of calling
ConnectionManager.broadcast directly, the domain-event listener
(app/websockets/listeners.py) publishes to a shared Redis channel, and
every process relays incoming messages to its own local
ConnectionManager via relay_to_local_clients. A broadcast published by
any one process is therefore delivered by all of them, including
itself — there's a single delivery path, not a local shortcut plus a
cross-process one.

publish() is also called from the Celery worker (AlertService runs
there too, via the periodic low-stock sweep), which is a different
concurrency model from the FastAPI app: Uvicorn runs the whole app on
one long-lived event loop, but Celery wraps each task in its own
`asyncio.run()` call, creating and destroying a fresh event loop every
time. A Redis client's connection pool binds asyncio primitives (locks,
futures) to whichever event loop first uses it, so reusing the same
client across two of those fresh loops fails with a "Future attached
to a different loop" error on the second call. publish() therefore
opens and closes a short-lived connection per call instead of reusing
a shared client, which is correct under both concurrency models at the
cost of one extra TCP handshake per publish — negligible next to the
alert/movement processing it accompanies. The persistent `redis`
client on this class is used only by relay_to_local_clients, which
never runs under Celery and lives for the FastAPI process's single
event loop, so reusing a connection there is both safe and desirable.
"""

import asyncio
import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings
from app.websockets.manager import ConnectionManager

logger = logging.getLogger(__name__)

BROADCAST_CHANNEL = "ws:broadcast"


class RedisBroadcaster:
    """Publishes WebSocket broadcast messages for every process to relay.

    Any process that reacts to a domain event — the FastAPI app
    handling a request, or (in principle) a Celery worker — can
    publish through an instance of this class, whether or not that
    process itself accepts WebSocket connections. Only a process that
    also runs relay_to_local_clients turns published messages back
    into actual local broadcasts.

    Attributes:
        redis: A dedicated, persistent Redis client used exclusively by
            relay_to_local_clients's long-lived subscription. Never
            used by publish() — see that method's docstring for why.
    """

    def __init__(self) -> None:
        """Initialize the broadcaster with its own Redis connection."""
        settings = get_settings()
        self._redis_url = settings.redis_url
        self.redis: Redis = Redis.from_url(self._redis_url, decode_responses=True)

    async def publish(self, message: dict[str, Any], channels: set[str]) -> None:
        """Publish a broadcast for every subscribed process to relay.

        Opens a short-lived Redis connection for this call alone
        instead of reusing `self.redis`, so this method stays safe to
        call from a fresh event loop each time — as the Celery worker
        does via `asyncio.run()` per task — without risking a
        cross-event-loop connection reuse error. See the module
        docstring for the full explanation.

        Args:
            message: A JSON-serializable payload.
            channels: The ConnectionManager channel(s) it applies to.
        """
        envelope = json.dumps({"message": message, "channels": list(channels)})
        async with Redis.from_url(self._redis_url, decode_responses=True) as client:
            await client.publish(BROADCAST_CHANNEL, envelope)

    async def close(self) -> None:
        """Release the dedicated Redis connection."""
        await self.redis.aclose()


async def relay_to_local_clients(
    broadcaster: RedisBroadcaster, connection_manager: ConnectionManager
) -> None:
    """Subscribe to the broadcast channel and relay messages to local clients.

    Runs until cancelled; intended to be launched as a background task
    for the lifetime of the FastAPI process (see app/main.py's
    lifespan). A malformed or unexpected message is logged and
    skipped rather than crashing the loop, since one bad message must
    not silence every future broadcast for the process's lifetime.

    Args:
        broadcaster: Provides the Redis connection to subscribe with.
        connection_manager: The local manager to relay messages into.
    """
    pubsub = broadcaster.redis.pubsub()
    await pubsub.subscribe(BROADCAST_CHANNEL)
    logger.info(
        "Subscribed to Redis channel '%s' for WebSocket fan-out.", BROADCAST_CHANNEL
    )
    try:
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            try:
                envelope = json.loads(raw["data"])
                await connection_manager.broadcast(
                    envelope["message"], set(envelope["channels"])
                )
            except Exception:
                logger.exception("Failed to relay a WebSocket broadcast message.")
    except asyncio.CancelledError:
        raise
    finally:
        await pubsub.unsubscribe(BROADCAST_CHANNEL)


_broadcaster = RedisBroadcaster()


def get_redis_broadcaster() -> RedisBroadcaster:
    """Return the process-wide RedisBroadcaster singleton.

    Returns:
        The shared RedisBroadcaster instance.
    """
    return _broadcaster
