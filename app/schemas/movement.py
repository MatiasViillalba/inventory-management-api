"""Pydantic schemas for the Movement resource.

Defines the request/response contracts for recording stock movements.
Movement records are immutable once created, so this module exposes a
create schema and a read schema only — no update schema exists.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.movement import MovementType
from app.schemas.common import ORMBaseSchema


class MovementCreate(BaseModel):
    """Payload for recording a new stock movement.

    Which warehouse fields are required depends on movement_type:
    IN requires destination_warehouse_id only, OUT requires
    source_warehouse_id only, and TRANSFER requires both.

    Attributes:
        product_id: The product whose stock is changing.
        movement_type: Whether stock is being added, removed, or moved.
        quantity: The amount of stock affected. Always positive.
        source_warehouse_id: Warehouse stock is removed from. Required
            for OUT and TRANSFER, must be omitted for IN.
        destination_warehouse_id: Warehouse stock is added to. Required
            for IN and TRANSFER, must be omitted for OUT.
        reason: Optional human-readable explanation for the movement.
    """

    product_id: uuid.UUID
    movement_type: MovementType
    quantity: int = Field(gt=0)
    source_warehouse_id: uuid.UUID | None = None
    destination_warehouse_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_warehouses_for_type(self) -> "MovementCreate":
        """Ensure the warehouse fields match what movement_type requires.

        Returns:
            The validated MovementCreate instance.

        Raises:
            ValueError: If a required warehouse field is missing or a
                disallowed one was provided for the given movement_type.
        """
        if self.movement_type == MovementType.IN:
            if self.destination_warehouse_id is None:
                raise ValueError(
                    "destination_warehouse_id is required for IN movements."
                )
            if self.source_warehouse_id is not None:
                raise ValueError(
                    "source_warehouse_id must not be set for IN movements."
                )
        elif self.movement_type == MovementType.OUT:
            if self.source_warehouse_id is None:
                raise ValueError("source_warehouse_id is required for OUT movements.")
            if self.destination_warehouse_id is not None:
                raise ValueError(
                    "destination_warehouse_id must not be set for OUT movements."
                )
        elif self.movement_type == MovementType.TRANSFER:
            if (
                self.source_warehouse_id is None
                or self.destination_warehouse_id is None
            ):
                raise ValueError(
                    "Both source_warehouse_id and destination_warehouse_id are "
                    "required for TRANSFER movements."
                )
            if self.source_warehouse_id == self.destination_warehouse_id:
                raise ValueError(
                    "source_warehouse_id and destination_warehouse_id must differ "
                    "for TRANSFER movements."
                )
        return self


class MovementRead(ORMBaseSchema):
    """Movement representation returned by the API.

    Attributes:
        id: Movement record primary key.
        product_id: The product whose stock changed.
        movement_type: Whether stock was added, removed, or moved.
        quantity: The amount of stock affected.
        source_warehouse_id: Warehouse stock was removed from, if any.
        destination_warehouse_id: Warehouse stock was added to, if any.
        reason: Human-readable explanation for the movement, if provided.
        performed_by: ID of the user who triggered the movement, if known.
        created_at: Timestamp when the movement was recorded.
    """

    id: uuid.UUID
    product_id: uuid.UUID
    movement_type: MovementType
    quantity: int
    source_warehouse_id: uuid.UUID | None
    destination_warehouse_id: uuid.UUID | None
    reason: str | None
    performed_by: uuid.UUID | None
    created_at: datetime
