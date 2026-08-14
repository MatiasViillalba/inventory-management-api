"""Movement history model.

Records every change to stock as an immutable audit entry. Unlike the
Inventory model (which holds the current snapshot), rows here are
never updated or deleted — they exist so any quantity change can be
traced back to who made it, when, and why.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class MovementType(str, enum.Enum):
    """The kind of stock change a movement record represents."""

    IN = "in"
    OUT = "out"
    TRANSFER = "transfer"


class Movement(BaseModel):
    """An immutable audit entry for a single stock change.

    Attributes:
        product_id: The product whose stock changed.
        movement_type: Whether stock was added, removed, or moved
            between warehouses.
        quantity: The amount of stock affected. Always positive; the
            direction is conveyed by movement_type and the warehouse
            fields below.
        source_warehouse_id: Warehouse stock was removed from. Set for
            OUT and TRANSFER movements, null for IN.
        destination_warehouse_id: Warehouse stock was added to. Set
            for IN and TRANSFER movements, null for OUT.
        reason: Optional human-readable explanation (e.g. "damaged
            goods", "purchase order #123").
        performed_by: ID of the user who triggered the movement. Not a
            foreign key yet since the User model does not exist until
            the JWT security commit.
    """

    __tablename__ = "movements"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, name="movement_type"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    source_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True
    )
    destination_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=True)
    performed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
