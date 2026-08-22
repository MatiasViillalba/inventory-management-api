"""Product model.

Represents a sellable item that can be stocked across multiple
warehouses. Inventory, movement, and alert records all reference a
product rather than duplicating its descriptive data.
"""

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Product(BaseModel):
    """A catalog item that is tracked and stored as inventory.

    Attributes:
        sku: Unique stock-keeping unit identifier.
        name: Human-readable product name.
        description: Optional longer description of the product.
        price: Unit sale price.
        is_active: Whether the product is currently sellable/stockable.
            Discontinued products are deactivated instead of deleted so
            historical movement records remain valid.
    """

    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=True)
    price: Mapped[Numeric] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
