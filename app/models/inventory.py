"""Inventory model.

Represents the current stock level of a product in a specific
warehouse. This is the mutable, queryable snapshot of "how much do we
have right now" — the immutable audit trail of how it got there lives
in the movement history model added in a later commit.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Inventory(BaseModel):
    """The stock level of a product within a warehouse.

    Attributes:
        product_id: Reference to the stocked product.
        warehouse_id: Reference to the warehouse holding the stock.
        quantity: Current stock quantity. Must never go negative;
            enforced at the service layer via InsufficientStockError.
        low_stock_threshold: Quantity below which a low-stock alert is
            triggered for this specific product/warehouse pair,
            overriding the global default from Settings.
    """

    __tablename__ = "inventories"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=True)
