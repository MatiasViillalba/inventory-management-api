"""Domain-event listener that broadcasts inventory activity over WebSockets.

Subscribes to the same in-process EventPublisher the domain services
publish to (see app/services/inventory_command.py and
app/services/alert.py) and forwards every inventory event to
ConnectionManager.broadcast, so a connected WebSocket client learns
about a stock change or alert the instant it happens instead of
polling the REST endpoints. register_websocket_listeners is called
once at application startup (see app/main.py).

Each event is additionally broadcast to the warehouse-scoped
channel(s) it's relevant to (one channel for most event types, two for
a transfer, which touches a source and a destination warehouse at
once), on top of the always-included global channel. Clients that only
care about one warehouse can subscribe to that warehouse's channel
(see app/api/v1/endpoints/websockets.py's `channel` query parameter)
instead of receiving every event in the system.
"""

import dataclasses
import datetime
import logging
import uuid
from typing import Any

from app.events.base import DomainEvent, EventPublisher
from app.events.inventory import (
    LowStockDetectedEvent,
    OutOfStockDetectedEvent,
    StockReceivedEvent,
    StockRemovedEvent,
    StockTransferredEvent,
)
from app.websockets.manager import ConnectionManager

logger = logging.getLogger(__name__)

# Mirrors each event class's own `event_type` property. Kept as a
# literal mapping, rather than instantiated at import time, since
# event_type is a stable string constant per class that doesn't
# depend on any instance data.
_BROADCAST_EVENT_TYPES = {
    StockReceivedEvent: "inventory.stock_received",
    StockRemovedEvent: "inventory.stock_removed",
    StockTransferredEvent: "inventory.stock_transferred",
    LowStockDetectedEvent: "inventory.low_stock_detected",
    OutOfStockDetectedEvent: "inventory.out_of_stock_detected",
}


def register_websocket_listeners(
    event_publisher: EventPublisher, connection_manager: ConnectionManager
) -> None:
    """Subscribe every inventory domain event to a WebSocket broadcast.

    Args:
        event_publisher: The publisher domain services publish to.
        connection_manager: The manager used to fan messages out to
            connected WebSocket clients.
    """

    async def broadcast_event(event: DomainEvent) -> None:
        """Forward one published domain event to its relevant WebSocket clients.

        Args:
            event: The published event.
        """
        await connection_manager.broadcast(_serialize_event(event), _channels_for(event))

    for event_type in _BROADCAST_EVENT_TYPES.values():
        event_publisher.subscribe(event_type, broadcast_event)
        logger.debug("Subscribed WebSocket broadcast to '%s'.", event_type)


def _channels_for(event: DomainEvent) -> set[str]:
    """Determine which warehouse-scoped channels an event is relevant to.

    Args:
        event: The published event.

    Returns:
        set[str]: The channel(s) to broadcast to, derived from the
        event's warehouse id field(s). Global-channel subscribers
        receive every event regardless of this set; that's handled by
        ConnectionManager.broadcast itself.
    """
    if isinstance(event, StockTransferredEvent):
        return {str(event.source_warehouse_id), str(event.destination_warehouse_id)}
    return {str(event.warehouse_id)}


def _serialize_event(event: DomainEvent) -> dict[str, Any]:
    """Convert a DomainEvent dataclass into a JSON-serializable dict.

    Args:
        event: The event to serialize.

    Returns:
        dict[str, Any]: The event's fields, with UUID and datetime
        values converted to their string representations.
    """
    payload: dict[str, Any] = {"event_type": event.event_type}
    for field in dataclasses.fields(event):
        value = getattr(event, field.name)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime.datetime):
            value = value.isoformat()
        payload[field.name] = value
    return payload
