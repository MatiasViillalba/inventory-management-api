"""Pydantic schemas for the Product resource.

Defines the request/response contracts used by the product API
endpoints, decoupled from the ProductRepository/SQLAlchemy model so
the persistence layer can evolve independently of the public API shape.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMBaseSchema


class ProductBase(BaseModel):
    """Fields shared by product create and update payloads.

    Attributes:
        sku: Unique stock-keeping unit identifier.
        name: Human-readable product name.
        description: Optional longer description of the product.
        price: Unit sale price. Must be strictly positive.
    """

    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal = Field(gt=0, decimal_places=2)


class ProductCreate(ProductBase):
    """Payload for creating a new product."""


class ProductUpdate(BaseModel):
    """Payload for partially updating an existing product.

    All fields are optional so clients can submit only the attributes
    they intend to change.
    """

    sku: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    is_active: bool | None = None


class ProductRead(ORMBaseSchema, ProductBase):
    """Product representation returned by the API.

    Attributes:
        id: Product primary key.
        is_active: Whether the product is currently sellable/stockable.
        created_at: Timestamp when the product was created.
        updated_at: Timestamp when the product was last updated.
    """

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
