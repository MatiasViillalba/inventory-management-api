"""Generic asynchronous repository providing base CRUD operations.

This module defines BaseRepository, a type-safe generic class that
encapsulates common data-access patterns (create, read, update, delete,
list) shared by every concrete repository in app/repositories/. Concrete
repositories subclass it to add model-specific queries while reusing
this shared implementation, keeping data-access logic DRY and
consistent across the domain.

Repositories never commit transactions themselves: the calling service
layer owns the unit of work and decides when to commit or roll back,
so multiple repository operations can be composed atomically.
"""

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import Base
from app.core.exceptions import NotFoundError

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic async repository implementing common CRUD operations.

    Subclasses provide the concrete SQLAlchemy model and inherit
    create, read, update, delete, and list behavior without duplicating
    query logic. Any query specific to a single aggregate (e.g. lookups
    by a natural key) belongs in the subclass, not here.

    Attributes:
        model: The SQLAlchemy declarative model class this repository
            manages.
        session: The active async database session used for all
            queries issued by this repository instance.
    """

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        """Initialize the repository with a model class and a session.

        Args:
            model: The SQLAlchemy declarative model class to operate on.
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain and shared across repositories
                within a single request/unit of work.
        """
        self.model = model
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelType | None:
        """Fetch a single entity by its primary key.

        Args:
            entity_id: The UUID primary key of the entity to fetch.

        Returns:
            The matching entity, or None if no row exists with that id.
        """
        return await self.session.get(self.model, entity_id)

    async def get_by_id_or_raise(self, entity_id: uuid.UUID) -> ModelType:
        """Fetch a single entity by its primary key, raising if absent.

        Args:
            entity_id: The UUID primary key of the entity to fetch.

        Returns:
            The matching entity.

        Raises:
            NotFoundError: If no row exists with the given id.
        """
        entity = await self.get_by_id(entity_id)
        if entity is None:
            raise NotFoundError(
                f"{self.model.__name__} with id '{entity_id}' was not found."
            )
        return entity

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[ModelType]:
        """List entities with basic offset/limit pagination.

        Args:
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of entities, ordered by database default order.
        """
        statement = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(self, entity: ModelType) -> ModelType:
        """Stage a new entity for insertion and flush it to the database.

        Args:
            entity: A fully constructed, unpersisted model instance.

        Returns:
            The same entity, refreshed with database-generated values
            (e.g. primary key defaults, server-side timestamps).
        """
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: ModelType) -> None:
        """Mark an entity for deletion and flush the change.

        Args:
            entity: The persisted model instance to delete.
        """
        await self.session.delete(entity)
        await self.session.flush()
