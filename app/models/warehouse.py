"""Warehouse model.

Represents a physical storage location that holds inventory. Every
stock record, movement, and transfer is scoped to a warehouse.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Warehouse(BaseModel):
    """A physical or logical location where product stock is stored.

    Attributes:
        name: Human-readable warehouse name.
        code: Short unique identifier used in reports and integrations.
        address: Physical address of the warehouse.
        is_active: Whether the warehouse currently participates in
            inventory operations. Inactive warehouses are kept for
            historical/audit purposes instead of being deleted.
    """

    __tablename__ = "warehouses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    address: Mapped[str] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
