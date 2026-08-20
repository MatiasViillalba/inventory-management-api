"""Business logic for inventory alerting.

AlertService keeps Alert records in sync with current stock levels. It
is invoked by the write side of inventory operations after a stock
mutation commits, rather than by API endpoints directly — alerts are a
reaction to inventory state, not a resource clients create by hand.

Newly created or escalated alerts also enqueue an email notification
task rather than sending it inline, so a slow or unavailable SMTP
server never delays the inventory mutation that triggered the alert.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.events.base import EventPublisher
from app.events.inventory import LowStockDetectedEvent, OutOfStockDetectedEvent
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.inventory import Inventory
from app.repositories.alert import AlertRepository
from app.tasks.notifications import send_low_stock_alert_email

logger = logging.getLogger(__name__)


class AlertService:
    """Creates, escalates, and resolves alerts based on stock levels.

    Attributes:
        session: The active async database session.
        repository: The data-access layer for Alert entities.
        event_publisher: Publisher used to announce newly created or
            escalated alerts to other parts of the system (e.g. the
            WebSocket broadcast listener).
    """

    def __init__(self, session: AsyncSession, event_publisher: EventPublisher) -> None:
        """Initialize the service with a database session and event publisher.

        Args:
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain.
            event_publisher: Publisher used to announce alert changes.
        """
        self.session = session
        self.repository = AlertRepository(session)
        self.event_publisher = event_publisher

    async def evaluate_stock_level(self, inventory: Inventory) -> Alert | None:
        """Reconcile alert state with a product's current stock level.

        Intended to be called right after an Inventory row is mutated.
        Below the applicable threshold, this creates a new active alert,
        escalates an existing LOW_STOCK alert to OUT_OF_STOCK once
        quantity reaches zero, or leaves a matching alert untouched.
        Once quantity recovers above the threshold, any active alert
        for the pair is auto-resolved.

        Args:
            inventory: The Inventory record to evaluate, read after its
                mutation has been applied.

        Returns:
            The active Alert reflecting the current condition, or None
            if stock is above threshold and no alert is active.
        """
        threshold = (
            inventory.low_stock_threshold
            if inventory.low_stock_threshold is not None
            else get_settings().low_stock_alert_threshold_default
        )
        existing = await self.repository.get_active_by_product_and_warehouse(
            inventory.product_id, inventory.warehouse_id
        )

        if inventory.quantity > threshold:
            if existing is not None:
                await self._resolve(existing)
            return None

        alert_type = (
            AlertType.OUT_OF_STOCK if inventory.quantity == 0 else AlertType.LOW_STOCK
        )

        if existing is not None:
            if existing.alert_type != alert_type:
                existing.alert_type = alert_type
                existing.quantity_at_trigger = inventory.quantity
                await self.session.commit()
                await self.session.refresh(existing)
                await self._react_to_alert(existing)
            return existing

        alert = Alert(
            product_id=inventory.product_id,
            warehouse_id=inventory.warehouse_id,
            alert_type=alert_type,
            threshold=threshold,
            quantity_at_trigger=inventory.quantity,
        )
        alert = await self.repository.create(alert)
        await self.session.commit()
        await self._react_to_alert(alert)
        return alert

    async def resolve_alert(self, alert_id: uuid.UUID) -> Alert:
        """Manually resolve an active alert.

        Args:
            alert_id: The alert's UUID.

        Returns:
            The resolved Alert.

        Raises:
            NotFoundError: If no alert exists with the given id.
            ConflictError: If the alert is already resolved.
        """
        alert = await self.repository.get_by_id_or_raise(alert_id)
        if alert.status == AlertStatus.RESOLVED:
            raise ConflictError(f"Alert '{alert_id}' is already resolved.")
        await self._resolve(alert)
        return alert

    async def list_active_alerts(self, skip: int = 0, limit: int = 100) -> list[Alert]:
        """List all currently active alerts.

        Args:
            skip: Number of records to skip from the start of the result set.
            limit: Maximum number of records to return.

        Returns:
            A list of active alerts.
        """
        return await self.repository.list_active(skip=skip, limit=limit)

    async def _react_to_alert(self, alert: Alert) -> None:
        """Publish a domain event and enqueue an email for a new/escalated alert.

        Args:
            alert: The newly created or escalated alert to react to.
        """
        event = (
            OutOfStockDetectedEvent(
                product_id=alert.product_id, warehouse_id=alert.warehouse_id
            )
            if alert.alert_type == AlertType.OUT_OF_STOCK
            else LowStockDetectedEvent(
                product_id=alert.product_id,
                warehouse_id=alert.warehouse_id,
                quantity=alert.quantity_at_trigger,
                threshold=alert.threshold,
            )
        )
        await self.event_publisher.publish(event)
        self._enqueue_notification(alert)

    def _enqueue_notification(self, alert: Alert) -> None:
        """Enqueue the low-stock email task without failing the caller.

        The alert row is already committed by this point, so a broker
        outage here must not surface as a failure of the inventory
        mutation that triggered it — it is logged and swallowed
        instead. The periodic sweep task (check_low_stock_levels) acts
        as a safety net that will re-evaluate this alert on its next
        run regardless.

        Args:
            alert: The newly created or escalated alert to notify about.
        """
        try:
            send_low_stock_alert_email.delay(str(alert.id))
        except Exception:
            logger.exception(
                "Failed to enqueue low-stock email notification for alert %s.",
                alert.id,
            )

    async def _resolve(self, alert: Alert) -> None:
        """Mark an alert resolved and stamp the resolution time.

        Args:
            alert: The alert to resolve, already loaded in this session.
        """
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(alert)
