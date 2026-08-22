"""Integration tests for the WebSocket connection/broadcast path.

Two layers are covered separately:

1. ConnectionManager's bookkeeping and fan-out logic (channel scoping,
   the always-included global channel, stale-connection pruning), using
   a minimal fake WebSocket instead of a real ASGI connection — this is
   pure in-memory logic with no I/O, so a stub keeps the tests fast and
   deterministic.
2. The actual /api/v1/ws route wired end-to-end, using Starlette's TestClient
   — httpx's ASGITransport (used by the `client` fixture everywhere
   else in this suite) does not support the WebSocket protocol, so
   these tests use TestClient instead, which does.

TestClient is instantiated without entering it as a context manager
(`TestClient(app)`, not `with TestClient(app) as c:`), which means the
app's lifespan never runs — the Redis pub/sub relay task and the
APScheduler heartbeat both stay off. That's deliberate: WebSocket
routing doesn't depend on lifespan, and skipping it keeps these tests
from depending on a live cross-thread Redis relay. What's verified
instead is the piece that actually belongs to this endpoint: accepting
a connection registers it with the shared ConnectionManager singleton,
and a broadcast reaches it. The event_publisher -> listener ->
RedisBroadcaster chain that feeds ConnectionManager in production is
exercised in tests/unit/test_services.py (event publishing) and covered
by app/websockets/listeners.py and pubsub.py's own design docs.

TestClient's websocket_connect() is synchronous, so bridging into the
async ConnectionManager.broadcast() uses asyncio.run() from the test's
own (non-async) main thread — safe here since, unlike in
test_celery_tasks.py, nothing is already running an event loop on this
thread.
"""

import asyncio
from typing import Any

from starlette.testclient import TestClient

from app.main import app
from app.websockets.manager import (
    GLOBAL_CHANNEL,
    ConnectionManager,
    get_connection_manager,
)


class _FakeWebSocket:
    """Minimal stand-in for a Starlette WebSocket, for pure-logic tests.

    Attributes:
        received: Every message successfully "sent" to this fake.
        fail_send: If True, send_json raises, simulating a dead
            connection ConnectionManager should prune.
    """

    def __init__(self, *, fail_send: bool = False) -> None:
        self.received: list[dict[str, Any]] = []
        self.fail_send = fail_send
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.fail_send:
            raise RuntimeError("connection closed")
        self.received.append(message)


class TestConnectionManager:
    """Tests for ConnectionManager's bookkeeping and broadcast fan-out."""

    async def test_connect_accepts_and_registers_the_connection(self) -> None:
        manager = ConnectionManager()
        websocket = _FakeWebSocket()

        await manager.connect(websocket, channel="warehouse-1")

        assert websocket.accepted is True
        assert websocket in manager._connections["warehouse-1"]

    async def test_disconnect_is_safe_when_never_connected(self) -> None:
        manager = ConnectionManager()

        manager.disconnect(_FakeWebSocket(), channel="never-connected")

    async def test_broadcast_delivers_only_to_matching_channel(self) -> None:
        manager = ConnectionManager()
        subscribed = _FakeWebSocket()
        other_channel = _FakeWebSocket()
        await manager.connect(subscribed, channel="warehouse-1")
        await manager.connect(other_channel, channel="warehouse-2")

        await manager.broadcast({"event_type": "test"}, {"warehouse-1"})

        assert subscribed.received == [{"event_type": "test"}]
        assert other_channel.received == []

    async def test_broadcast_always_reaches_global_subscribers(self) -> None:
        manager = ConnectionManager()
        global_subscriber = _FakeWebSocket()
        scoped_subscriber = _FakeWebSocket()
        await manager.connect(global_subscriber, channel=GLOBAL_CHANNEL)
        await manager.connect(scoped_subscriber, channel="warehouse-1")

        await manager.broadcast({"event_type": "test"}, {"warehouse-1"})

        assert global_subscriber.received == [{"event_type": "test"}]
        assert scoped_subscriber.received == [{"event_type": "test"}]

    async def test_broadcast_prunes_connections_that_fail_to_send(self) -> None:
        manager = ConnectionManager()
        dead = _FakeWebSocket(fail_send=True)
        await manager.connect(dead, channel="warehouse-1")

        await manager.broadcast({"event_type": "test"}, {"warehouse-1"})

        assert "warehouse-1" not in manager._connections


class TestWebSocketEndpoint:
    """Tests for the /ws route's connection lifecycle and broadcast delivery."""

    def test_connecting_registers_with_the_shared_connection_manager(self) -> None:
        client = TestClient(app)
        manager = get_connection_manager()

        with client.websocket_connect("/api/v1/ws?channel=endpoint-test-1"):
            assert len(manager._connections.get("endpoint-test-1", set())) == 1

        assert "endpoint-test-1" not in manager._connections

    def test_broadcast_to_subscribed_channel_is_received(self) -> None:
        client = TestClient(app)
        manager = get_connection_manager()

        with client.websocket_connect(
            "/api/v1/ws?channel=endpoint-test-2"
        ) as websocket:
            asyncio.run(
                manager.broadcast({"event_type": "stock_received"}, {"endpoint-test-2"})
            )
            message = websocket.receive_json()

        assert message == {"event_type": "stock_received"}

    def test_broadcast_to_a_different_channel_is_not_delivered_first(self) -> None:
        client = TestClient(app)
        manager = get_connection_manager()

        with client.websocket_connect(
            "/api/v1/ws?channel=endpoint-test-3"
        ) as websocket:
            asyncio.run(
                manager.broadcast({"event_type": "irrelevant"}, {"unrelated-channel"})
            )
            asyncio.run(
                manager.broadcast({"event_type": "relevant"}, {"endpoint-test-3"})
            )
            message = websocket.receive_json()

        assert message == {"event_type": "relevant"}

    def test_default_channel_is_global(self) -> None:
        client = TestClient(app)
        manager = get_connection_manager()

        with client.websocket_connect("/api/v1/ws") as websocket:
            assert GLOBAL_CHANNEL in manager._connections
            asyncio.run(
                manager.broadcast({"event_type": "global_ping"}, {GLOBAL_CHANNEL})
            )
            message = websocket.receive_json()

        assert message == {"event_type": "global_ping"}
