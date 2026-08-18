"""Repository for Alert data access.

Extends BaseRepository with query methods specific to the Alert
aggregate: lookup of the currently active alert for a product/warehouse
pair, used to avoid raising duplicate alerts for the same condition,
and listing of all active alerts for the alerts dashboard.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus
from app.repositories.base import BaseRepository


class AlertRepository(BaseRepository[Alert]):
    """Data-access layer for Alert entities.

    Attributes:
        session: The active async database session, inherited from
            BaseRepository.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository bound to the Alert model.

        Args:
            session: An active AsyncSession injected by the caller.
        """
        super().__init__(Alert, session)

    async def get_active_by_product_and_warehouse(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Alert | None:
        """Fetch the currently active alert for a product/warehouse pair.

        A product/warehouse pair should never have more than one active
        alert at a time: AlertService escalates or clears the existing
        one instead of creating a second.

        Args:
            product_id: The product's UUID.
            warehouse_id: The warehouse's UUID.

        Returns:
            The active Alert for that pair, or None if there isn't one.
        """
        statement = select(Alert).where(
            Alert.product_id == product_id,
            Alert.warehouse_id == warehouse_id,
            Alert.status == AlertStatus.ACTIVE,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Alert]:
        """List all currently active alerts.

        Args:
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of active alerts.
        """
        statement = (
            select(Alert)
            .where(Alert.status == AlertStatus.ACTIVE)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
