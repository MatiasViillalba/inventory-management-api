"""Alert model.

Represents a notification triggered by an inventory condition, such as
stock falling below its configured threshold. Alerts are persisted so
they can be listed, deduplicated, and audited, in addition to being
pushed in real time over WebSockets and email.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AlertType(str, enum.Enum):
    """The condition that triggered an alert."""

    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"


class AlertStatus(str, enum.Enum):
    """The current lifecycle state of an alert."""

    ACTIVE = "active"
    RESOLVED = "resolved"


class Alert(BaseModel):
    """A stock-condition notification for a product in a warehouse.

    Attributes:
        product_id: The product that triggered the alert.
        warehouse_id: The warehouse where the condition occurred.
        alert_type: The kind of condition that was detected.
        status: Whether the alert is still active or has been resolved
            (e.g. after restocking).
        threshold: The stock threshold that was breached.
        quantity_at_trigger: The stock quantity at the moment the
            alert was created, kept for historical reference.
        resolved_at: Timestamp when the alert transitioned to
            RESOLVED, null while still active.
    """

    __tablename__ = "alerts"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    alert_type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, name="alert_type"), nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="alert_status"),
        default=AlertStatus.ACTIVE,
        nullable=False,
    )
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_at_trigger: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
