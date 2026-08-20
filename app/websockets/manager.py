"""In-process WebSocket connection manager.

Tracks every currently connected WebSocket client and provides
broadcast helpers. Connections are grouped by an optional channel name
(e.g. a warehouse id) so a client only interested in one warehouse's
activity isn't sent updates about every other one; a client that
subscribes to GLOBAL_CHANNEL instead receives every broadcast
regardless of channel. Route handlers that accept incoming
connections, and the domain-event listener that feeds broadcasts from
inventory activity, are wired up in later commits — this module only
owns connection bookkeeping and message fan-out.
"""

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

GLOBAL_CHANNEL = "global"


class ConnectionManager:
    """Tracks active WebSocket connections grouped by channel.

    Not safe to share across multiple API processes: state lives only
    in this process's memory, so a broadcast reaches connections
    accepted by this instance alone. Fanning broadcasts out across
    multiple processes is handled by the Redis pub/sub layer added in
    a later commit, which this manager will sit behind.

    Attributes:
        _connections: Maps each channel name to the set of WebSocket
            connections currently subscribed to it.
    """

    def __init__(self) -> None:
        """Initialize the manager with no active connections."""
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str = GLOBAL_CHANNEL) -> None:
        """Accept a WebSocket handshake and register it under a channel.

        Args:
            websocket: The incoming, not-yet-accepted WebSocket connection.
            channel: The channel to subscribe this connection to.
                Defaults to the global channel.
        """
        await websocket.accept()
        self._connections.setdefault(channel, set()).add(websocket)
        logger.info(
            "WebSocket connected on channel '%s' (%d active).",
            channel,
            len(self._connections[channel]),
        )

    def disconnect(self, websocket: WebSocket, channel: str = GLOBAL_CHANNEL) -> None:
        """Remove a WebSocket connection from a channel.

        Safe to call even if the connection was already removed or
        never registered, so callers can use it unconditionally during
        error-handling cleanup.

        Args:
            websocket: The connection to remove.
            channel: The channel it was subscribed to.
        """
        connections = self._connections.get(channel)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            del self._connections[channel]

    async def broadcast(self, message: dict[str, Any], channel: str = GLOBAL_CHANNEL) -> None:
        """Send a JSON message to a channel's subscribers and the global ones.

        A connection that fails to receive the message (e.g. because
        it disconnected without a clean close handshake) is dropped
        from every channel rather than left to error again on the next
        broadcast.

        Args:
            message: A JSON-serializable payload to send.
            channel: The channel to broadcast to.
        """
        targets = set(self._connections.get(channel, set()))
        if channel != GLOBAL_CHANNEL:
            targets |= self._connections.get(GLOBAL_CHANNEL, set())

        stale: list[WebSocket] = []
        for connection in targets:
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)

        for connection in stale:
            self.disconnect(connection, channel)
            self.disconnect(connection, GLOBAL_CHANNEL)


_connection_manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Return the process-wide ConnectionManager singleton.

    A single shared instance is required, unlike get_db's per-request
    session, so that connections accepted on one request stay
    reachable by broadcasts triggered from any other.

    Returns:
        The shared ConnectionManager instance.
    """
    return _connection_manager
