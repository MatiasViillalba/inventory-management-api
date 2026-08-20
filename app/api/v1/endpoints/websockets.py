"""WebSocket endpoint for real-time inventory notifications.

Clients connect to receive a live feed of inventory events (stock
changes, alerts) as they happen, instead of polling the REST endpoints.
This route only owns the connection lifecycle; what actually gets
broadcast over it is wired up in later commits, where domain events are
subscribed to ConnectionManager.broadcast.
"""

import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.websockets.manager import GLOBAL_CHANNEL, ConnectionManager, get_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    channel: str = Query(
        default=GLOBAL_CHANNEL,
        description=(
            "Channel to subscribe to, e.g. a warehouse id for "
            "warehouse-scoped updates. Defaults to the global channel, "
            "which receives every broadcast."
        ),
    ),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> None:
    """Accept a WebSocket connection and keep it open for broadcasts.

    This endpoint is broadcast-only: it does not act on messages the
    client sends, it only reads them to detect when the client closes
    the connection. Sending is driven entirely by
    ConnectionManager.broadcast, called from elsewhere in the app.

    Args:
        websocket: The incoming WebSocket connection.
        channel: The channel to subscribe to, from the `channel` query
            parameter.
        manager: Injected process-wide ConnectionManager.
    """
    await manager.connect(websocket, channel=channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected from channel '%s'.", channel)
    finally:
        manager.disconnect(websocket, channel=channel)
