"""Pydantic schemas for the Warehouse resource.

Defines the request/response contracts used by the warehouse API
endpoints, decoupled from the WarehouseRepository/SQLAlchemy model so
the persistence layer can evolve independently of the public API shape.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBaseSchema


class WarehouseBase(BaseModel):
    """Fields shared by warehouse create and update payloads.

    Attributes:
        name: Human-readable warehouse name.
        code: Short unique identifier used in reports and integrations.
        address: Physical address of the warehouse.
    """

    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=20)
    address: str | None = Field(default=None, max_length=500)


class WarehouseCreate(WarehouseBase):
    """Payload for creating a new warehouse."""


class WarehouseUpdate(BaseModel):
    """Payload for partially updating an existing warehouse.

    All fields are optional so clients can submit only the attributes
    they intend to change.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class WarehouseRead(ORMBaseSchema, WarehouseBase):
    """Warehouse representation returned by the API.

    Attributes:
        id: Warehouse primary key.
        is_active: Whether the warehouse currently participates in
            inventory operations.
        created_at: Timestamp when the warehouse was created.
        updated_at: Timestamp when the warehouse was last updated.
    """

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
