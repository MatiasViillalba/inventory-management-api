"""Shared base model mixin for all ORM models.

This module defines BaseModel, which every domain model in app/models/
inherits from alongside the declarative Base, so that primary keys and
audit timestamps stay consistent across the entire schema.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class BaseModel(Base):
    """Abstract base class providing a UUID primary key and audit timestamps.

    Attributes:
        id: Primary key, generated client-side as a UUID4.
        created_at: Timestamp set once when the row is inserted.
        updated_at: Timestamp refreshed automatically on every update.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
