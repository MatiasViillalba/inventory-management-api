"""Declarative base for SQLAlchemy models.

This module defines the shared declarative base class that all ORM
models in the application inherit from. Keeping it isolated in its own
module (separate from session.py and the models themselves) avoids
circular imports between models and the database session setup.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base class for all SQLAlchemy ORM models.

    All models in app/models/ must inherit from this class so that
    Alembic can autodetect them for migrations and so that SQLAlchemy's
    metadata registry stays consistent across the application.
    """

    pass
