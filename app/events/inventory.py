"""Domain events for the Inventory aggregate.

Concrete DomainEvent subclasses raised by the inventory write side
(InventoryCommandService) for stock-mutating movements, and by the
alerting subsystem (AlertService) for threshold conditions. Raising and
constructing these events is separate from publishing them: publishing
goes through EventPublisher (app/events/publisher.py), wired into the
services in a later commit.
"""

import uuid
from dataclasses import dataclass

from app.events.base import DomainEvent


@dataclass(frozen=True, kw_only=True)
class StockReceivedEvent(DomainEvent):
    """Raised when stock is added to a warehouse (an IN movement).

    Attributes:
        product_id: The product whose stock increased.
        warehouse_id: The warehouse that received the stock.
        quantity: The amount received.
        resulting_quantity: The warehouse's stock level after the change.
    """

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int
    resulting_quantity: int

    @property
    def event_type(self) -> str:
        """Stable routing key for this event. See DomainEvent.event_type."""
        return "inventory.stock_received"


@dataclass(frozen=True, kw_only=True)
class StockRemovedEvent(DomainEvent):
    """Raised when stock is removed from a warehouse (an OUT movement).

    Attributes:
        product_id: The product whose stock decreased.
        warehouse_id: The warehouse the stock was removed from.
        quantity: The amount removed.
        resulting_quantity: The warehouse's stock level after the change.
    """

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int
    resulting_quantity: int

    @property
    def event_type(self) -> str:
        """Stable routing key for this event. See DomainEvent.event_type."""
        return "inventory.stock_removed"


@dataclass(frozen=True, kw_only=True)
class StockTransferredEvent(DomainEvent):
    """Raised when stock moves between two warehouses (a TRANSFER movement).

    Attributes:
        product_id: The product that was moved.
        source_warehouse_id: The warehouse stock was removed from.
        destination_warehouse_id: The warehouse stock was added to.
        quantity: The amount transferred.
    """

    product_id: uuid.UUID
    source_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    quantity: int

    @property
    def event_type(self) -> str:
        """Stable routing key for this event. See DomainEvent.event_type."""
        return "inventory.stock_transferred"


@dataclass(frozen=True, kw_only=True)
class LowStockDetectedEvent(DomainEvent):
    """Raised when a product/warehouse pair drops to or below its threshold.

    Attributes:
        product_id: The affected product.
        warehouse_id: The affected warehouse.
        quantity: The stock quantity that triggered the alert.
        threshold: The low-stock threshold that was breached.
    """

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int
    threshold: int

    @property
    def event_type(self) -> str:
        """Stable routing key for this event. See DomainEvent.event_type."""
        return "inventory.low_stock_detected"


@dataclass(frozen=True, kw_only=True)
class OutOfStockDetectedEvent(DomainEvent):
    """Raised when a product/warehouse pair's stock reaches zero.

    Attributes:
        product_id: The affected product.
        warehouse_id: The affected warehouse.
    """

    product_id: uuid.UUID
    warehouse_id: uuid.UUID

    @property
    def event_type(self) -> str:
        """Stable routing key for this event. See DomainEvent.event_type."""
        return "inventory.out_of_stock_detected"
