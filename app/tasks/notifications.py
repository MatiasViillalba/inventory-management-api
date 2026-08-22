"""Celery task for emailing low-stock alert notifications.

Triggered from the alert-raising flow with just an alert id, so the
task itself owns loading the related Alert, Product, and Warehouse
records and rendering them into an email. Recipients are every active
superuser, since the domain has no dedicated notification-recipient
concept yet.
"""

import asyncio
import logging
import uuid

from app.core.email import send_email
from app.core.session import TaskSessionLocal
from app.models.alert import Alert, AlertType
from app.repositories.alert import AlertRepository
from app.repositories.product import ProductRepository
from app.repositories.user import UserRepository
from app.repositories.warehouse import WarehouseRepository
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.notifications.send_low_stock_alert_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_low_stock_alert_email(alert_id: str) -> None:
    """Email active superusers about a low-stock or out-of-stock alert.

    Entry point invoked asynchronously by AlertService right after an
    alert is created or escalated, so notification delivery never
    blocks the request/event that raised the alert. Retries up to 3
    times with exponential backoff if the SMTP server is temporarily
    unreachable.

    Args:
        alert_id: String form of the Alert's UUID. Passed as a string,
            not a UUID, since Celery task arguments are JSON-serialized.
    """
    asyncio.run(_send_low_stock_alert_email(uuid.UUID(alert_id)))


async def _send_low_stock_alert_email(alert_id: uuid.UUID) -> None:
    """Async implementation: load context, render, and send the email.

    Args:
        alert_id: The Alert's UUID.
    """
    async with TaskSessionLocal() as session:
        alert = await AlertRepository(session).get_by_id_or_raise(alert_id)
        product = await ProductRepository(session).get_by_id_or_raise(alert.product_id)
        warehouse = await WarehouseRepository(session).get_by_id_or_raise(
            alert.warehouse_id
        )
        recipients = [
            user.email
            for user in await UserRepository(session).list_active_superusers()
        ]

    if not recipients:
        logger.warning(
            "No active superusers to notify for alert %s; skipping email.", alert_id
        )
        return

    subject = _build_subject(alert, product_name=product.name)
    body = _build_body(alert, product_name=product.name, warehouse_name=warehouse.name)
    send_email(to=recipients, subject=subject, body=body)


def _build_subject(alert: Alert, *, product_name: str) -> str:
    """Compose the email subject line for an alert notification.

    Args:
        alert: The alert being notified about.
        product_name: The affected product's display name.

    Returns:
        A subject line indicating alert severity and the affected product.
    """
    label = (
        "OUT OF STOCK" if alert.alert_type == AlertType.OUT_OF_STOCK else "Low Stock"
    )
    return f"[Inventory Alert] {label}: {product_name}"


def _build_body(alert: Alert, *, product_name: str, warehouse_name: str) -> str:
    """Compose the plain-text email body for an alert notification.

    Args:
        alert: The alert being notified about.
        product_name: The affected product's display name.
        warehouse_name: The affected warehouse's display name.

    Returns:
        A human-readable summary of the alert condition.
    """
    return (
        f"Product: {product_name}\n"
        f"Warehouse: {warehouse_name}\n"
        f"Alert type: {alert.alert_type.value}\n"
        f"Current quantity: {alert.quantity_at_trigger}\n"
        f"Threshold: {alert.threshold}\n"
        f"Triggered at: {alert.created_at.isoformat()}\n"
    )
