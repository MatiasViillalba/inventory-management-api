"""Write-side (CQRS command) business logic for inventory.

InventoryCommandService is the write half of the CQRS split for the
Inventory aggregate: it applies stock changes under row-level locking
and appends the resulting audit trail. The read half, which only
queries current stock levels and never mutates them, lives in
InventoryQueryService (app/services/inventory_query.py) — see that
module's docstring for the rationale behind the split.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientStockError, NotFoundError
from app.models.inventory import Inventory
from app.models.movement import Movement, MovementType
from app.repositories.inventory import InventoryRepository
from app.repositories.movement import MovementRepository
from app.repositories.product import ProductRepository
from app.repositories.warehouse import WarehouseRepository
from app.schemas.movement import MovementCreate


class InventoryCommandService:
    """Applies stock-mutating operations and records their audit trail.

    Every public method executes inside a single transaction: it locks
    the affected Inventory row(s) with SELECT ... FOR UPDATE, validates
    the resulting quantity, mutates it, appends an immutable Movement
    record, and commits. If any step raises, the caller's session
    rollback leaves stock and history consistent with each other.

    Attributes:
        session: The active async database session.
        inventory_repository: Data-access layer for Inventory entities.
        movement_repository: Data-access layer for Movement entities.
        product_repository: Data-access layer for Product entities, used
            to validate that a movement's product exists.
        warehouse_repository: Data-access layer for Warehouse entities,
            used to validate that a movement's warehouse(s) exist.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain.
        """
        self.session = session
        self.inventory_repository = InventoryRepository(session)
        self.movement_repository = MovementRepository(session)
        self.product_repository = ProductRepository(session)
        self.warehouse_repository = WarehouseRepository(session)

    async def record_movement(
        self, data: MovementCreate, performed_by: uuid.UUID | None = None
    ) -> Movement:
        """Apply a stock movement and persist its immutable audit record.

        Args:
            data: Validated movement payload. Which warehouse fields are
                populated depends on data.movement_type — see
                MovementCreate for the exact rules.
            performed_by: ID of the user triggering the movement, or
                None if triggered by an unauthenticated/system context.

        Returns:
            The newly created Movement record.

        Raises:
            NotFoundError: If the product, or a referenced warehouse,
                does not exist.
            InsufficientStockError: If an OUT or TRANSFER movement
                would reduce a stock level below zero.
        """
        await self.product_repository.get_by_id_or_raise(data.product_id)

        if data.movement_type == MovementType.IN:
            await self._increase_stock(
                data.product_id, data.destination_warehouse_id, data.quantity
            )
        elif data.movement_type == MovementType.OUT:
            await self._decrease_stock(
                data.product_id, data.source_warehouse_id, data.quantity
            )
        else:
            await self._transfer_stock(
                data.product_id,
                data.source_warehouse_id,
                data.destination_warehouse_id,
                data.quantity,
            )

        movement = Movement(
            product_id=data.product_id,
            movement_type=data.movement_type,
            quantity=data.quantity,
            source_warehouse_id=data.source_warehouse_id,
            destination_warehouse_id=data.destination_warehouse_id,
            reason=data.reason,
            performed_by=performed_by,
        )
        movement = await self.movement_repository.create(movement)
        await self.session.commit()
        return movement

    async def _transfer_stock(
        self,
        product_id: uuid.UUID,
        source_warehouse_id: uuid.UUID,
        destination_warehouse_id: uuid.UUID,
        quantity: int,
    ) -> None:
        """Move stock between two warehouses as a single locked operation.

        The two legs are always applied in a fixed order — by comparing
        the warehouse UUIDs, not by which one is source/destination —
        so that two concurrent transfers between the same warehouse
        pair in opposite directions always acquire their row locks in
        the same global order and can never deadlock on each other.

        Args:
            product_id: The product's UUID.
            source_warehouse_id: Warehouse stock is removed from.
            destination_warehouse_id: Warehouse stock is added to.
            quantity: The amount to move. Always positive.

        Raises:
            NotFoundError: If either warehouse, or the source's stock
                record for this product, does not exist.
            InsufficientStockError: If quantity exceeds the source's
                current stock level.
        """
        first_id, second_id = sorted(
            (source_warehouse_id, destination_warehouse_id), key=str
        )
        if first_id == source_warehouse_id:
            await self._decrease_stock(product_id, source_warehouse_id, quantity)
            await self._increase_stock(product_id, destination_warehouse_id, quantity)
        else:
            await self._increase_stock(product_id, destination_warehouse_id, quantity)
            await self._decrease_stock(product_id, source_warehouse_id, quantity)

    async def _increase_stock(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, quantity: int
    ) -> Inventory:
        """Lock and increase a stock level, creating the record if absent.

        Args:
            product_id: The product's UUID.
            warehouse_id: The destination warehouse's UUID.
            quantity: The amount to add. Always positive.

        Returns:
            The updated (or newly created) Inventory record.

        Raises:
            NotFoundError: If the warehouse does not exist.
        """
        await self.warehouse_repository.get_by_id_or_raise(warehouse_id)

        inventory = await self.inventory_repository.get_by_product_and_warehouse_for_update(
            product_id, warehouse_id
        )
        if inventory is None:
            inventory = await self.inventory_repository.create(
                Inventory(product_id=product_id, warehouse_id=warehouse_id, quantity=0)
            )
        inventory.quantity += quantity
        await self.session.flush()
        return inventory

    async def _decrease_stock(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, quantity: int
    ) -> Inventory:
        """Lock and decrease a stock level, rejecting negative results.

        Args:
            product_id: The product's UUID.
            warehouse_id: The source warehouse's UUID.
            quantity: The amount to remove. Always positive.

        Returns:
            The updated Inventory record.

        Raises:
            NotFoundError: If the warehouse, or its stock record for
                this product, does not exist.
            InsufficientStockError: If quantity exceeds the current
                stock level.
        """
        await self.warehouse_repository.get_by_id_or_raise(warehouse_id)

        inventory = await self.inventory_repository.get_by_product_and_warehouse_for_update(
            product_id, warehouse_id
        )
        if inventory is None:
            raise NotFoundError(
                f"No inventory record for product '{product_id}' in "
                f"warehouse '{warehouse_id}'."
            )
        if inventory.quantity < quantity:
            raise InsufficientStockError(
                f"Cannot remove {quantity} units of product '{product_id}' from "
                f"warehouse '{warehouse_id}': only {inventory.quantity} in stock."
            )
        inventory.quantity -= quantity
        await self.session.flush()
        return inventory
