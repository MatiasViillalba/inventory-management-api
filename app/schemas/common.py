"""Shared schema building blocks.

Defines base configuration and generic pagination models reused across
every domain-specific schema module in app/schemas/, so ORM-mapping
behavior and pagination shape stay consistent across the whole API.
"""

from pydantic import BaseModel, ConfigDict


class ORMBaseSchema(BaseModel):
    """Base schema for read models that are populated from ORM objects.

    Enabling from_attributes allows these schemas to be constructed
    directly from SQLAlchemy model instances (e.g. Warehouse, Product)
    instead of requiring a manual dict conversion at every call site.
    """

    model_config = ConfigDict(from_attributes=True)


class PaginationParams(BaseModel):
    """Common offset/limit pagination query parameters.

    Attributes:
        skip: Number of records to skip from the start of the result set.
        limit: Maximum number of records to return in a single page.
    """

    skip: int = 0
    limit: int = 100
