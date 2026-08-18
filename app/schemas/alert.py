"""Pydantic schemas for the Alert resource.

Alerts are created internally by AlertService in reaction to inventory
conditions, never directly by API clients. This module therefore
exposes only a read model; the sole client-triggered mutation is
resolving an active alert, handled at the service layer without a
dedicated request body.
"""

import uuid
from datetime import datetime

from app.models.alert import AlertStatus, AlertType
from app.schemas.common import ORMBaseSchema


class AlertRead(ORMBaseSchema):
    """Alert representation returned by the API.

    Attributes:
        id: Alert primary key.
        product_id: The product that triggered the alert.
        warehouse_id: The warehouse where the condition occurred.
        alert_type: The kind of condition that was detected.
        status: Whether the alert is still active or has been resolved.
        threshold: The stock threshold that was breached.
        quantity_at_trigger: The stock quantity at the moment the alert
            was created.
        resolved_at: Timestamp when the alert was resolved, if any.
        created_at: Timestamp when the alert was created.
    """

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    alert_type: AlertType
    status: AlertStatus
    threshold: int
    quantity_at_trigger: int
    resolved_at: datetime | None
    created_at: datetime
