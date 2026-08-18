"""Base classes for the application's domain event system.

Defines the event-driven building blocks shared by every concrete event
and publisher in the codebase: an immutable DomainEvent envelope, and
the EventPublisher/EventHandler contracts that decouple event producers
(services) from consumers (concrete publisher implementations,
in-process handlers, external subscribers).

Concrete domain events for the Inventory aggregate live in
app/events/inventory.py; the concrete publisher implementation lives in
app/events/publisher.py.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Immutable base for every event raised by the domain layer.

    Subclasses are themselves frozen dataclasses that add
    event-specific payload fields; this base only carries the envelope
    metadata every event needs regardless of what happened.

    Attributes:
        event_id: Unique identifier for this event occurrence, distinct
            from the id of whatever aggregate it describes.
        occurred_at: UTC timestamp captured when the event was
            constructed, not when it is eventually published or
            handled.
    """

    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def event_type(self) -> str:
        """A stable, human-readable name identifying this event's kind.

        Used as the routing key/topic name by EventPublisher
        implementations, so concrete subclasses must override this with
        a value that stays stable across releases even if the Python
        class name changes.

        Returns:
            The event type name, e.g. "inventory.stock_increased".

        Raises:
            NotImplementedError: If a concrete subclass does not
                override this property.
        """
        raise NotImplementedError(f"{type(self).__name__} must define event_type.")


class EventHandler(Protocol):
    """Callable contract for a function that reacts to a DomainEvent."""

    async def __call__(self, event: DomainEvent) -> None:
        """Handle a single published event.

        Args:
            event: The event instance to react to.
        """
        ...


class EventPublisher(ABC):
    """Interface for publishing domain events to interested subscribers.

    Kept separate from any specific transport so services depend only
    on this abstraction rather than on a concrete broker. The concrete
    implementation (e.g. an in-process dispatcher or a Redis pub/sub
    publisher) lives in app/events/publisher.py and is wired into
    services via dependency injection.
    """

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        """Publish a single event to every subscriber of its type.

        Args:
            event: The event instance to publish.
        """
        raise NotImplementedError

    @abstractmethod
    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler to run whenever a matching event is published.

        Args:
            event_type: The event_type name to listen for.
            handler: An async callable invoked with each matching event.
        """
        raise NotImplementedError
