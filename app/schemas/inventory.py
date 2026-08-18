"""Pydantic schemas for the Inventory resource.

Inventory records are never created directly by clients — they are
created and mutated as a side effect of Movement operations, handled
by InventoryService. This module therefore exposes only a read model
and a schema for adjusting the per-record low-stock threshold.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBaseSchema


class InventoryRead(ORMBaseSchema):
    """Inventory representation returned by the API.

    Attributes:
        id: Inventory record primary key.
        product_id: The stocked product.
        warehouse_id: The warehouse holding the stock.
        quantity: Current stock quantity.
        low_stock_threshold: Quantity below which a low-stock alert is
            triggered for this specific product/warehouse pair.
        created_at: Timestamp when the record was created.
        updated_at: Timestamp when the record was last updated.
    """

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int
    low_stock_threshold: int | None
    created_at: datetime
    updated_at: datetime


class InventoryThresholdUpdate(BaseModel):
    """Payload for setting a record-specific low-stock threshold.

    Attributes:
        low_stock_threshold: New threshold value; must be non-negative.
    """

    low_stock_threshold: int = Field(ge=0)
