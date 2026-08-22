"""Write-side (CQRS command) business logic for inventory.

InventoryCommandService is the write half of the CQRS split for the
Inventory aggregate: it applies stock changes under row-level locking
and appends the resulting audit trail. The read half, which only
queries current stock levels and never mutates them, lives in
InventoryQueryService (app/services/inventory_query.py) — see that
module's docstring for the rationale behind the split.

After a movement commits, this service also reconciles alert state for
every inventory row it touched (via AlertService) and publishes a
domain event describing the movement, so the WebSocket broadcast
listener and any other subscriber learn about stock changes as they
happen rather than by polling.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientStockError, NotFoundError
from app.events.base import EventPublisher
from app.events.inventory import (
    StockReceivedEvent,
    StockRemovedEvent,
    StockTransferredEvent,
)
from app.models.inventory import Inventory
from app.models.movement import Movement, MovementType
from app.repositories.inventory import InventoryRepository
from app.repositories.movement import MovementRepository
from app.repositories.product import ProductRepository
from app.repositories.warehouse import WarehouseRepository
from app.schemas.movement import MovementCreate
from app.services.alert import AlertService


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
        event_publisher: Publisher used to announce completed movements.
        alert_service: Reconciles alert state for inventory rows this
            service mutates, sharing the same session and publisher.
    """

    def __init__(self, session: AsyncSession, event_publisher: EventPublisher) -> None:
        """Initialize the service with a database session and event publisher.

        Args:
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain.
            event_publisher: Publisher used to announce completed
                movements and, via AlertService, alert changes.
        """
        self.session = session
        self.event_publisher = event_publisher
        self.inventory_repository = InventoryRepository(session)
        self.movement_repository = MovementRepository(session)
        self.product_repository = ProductRepository(session)
        self.warehouse_repository = WarehouseRepository(session)
        self.alert_service = AlertService(session, event_publisher)

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

        affected: list[Inventory]
        if data.movement_type == MovementType.IN:
            # MovementCreate.validate_warehouses_for_type guarantees
            # destination_warehouse_id is set for IN; the assert makes
            # that runtime invariant visible to the type checker too.
            assert data.destination_warehouse_id is not None
            inventory = await self._increase_stock(
                data.product_id, data.destination_warehouse_id, data.quantity
            )
            affected = [inventory]
        elif data.movement_type == MovementType.OUT:
            assert data.source_warehouse_id is not None
            inventory = await self._decrease_stock(
                data.product_id, data.source_warehouse_id, data.quantity
            )
            affected = [inventory]
        else:
            assert data.source_warehouse_id is not None
            assert data.destination_warehouse_id is not None
            source_inventory, destination_inventory = await self._transfer_stock(
                data.product_id,
                data.source_warehouse_id,
                data.destination_warehouse_id,
                data.quantity,
            )
            affected = [source_inventory, destination_inventory]

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

        for inventory in affected:
            await self.alert_service.evaluate_stock_level(inventory)
        await self.event_publisher.publish(self._build_movement_event(data, affected))

        return movement

    def _build_movement_event(
        self, data: MovementCreate, affected: list[Inventory]
    ) -> StockReceivedEvent | StockRemovedEvent | StockTransferredEvent:
        """Build the domain event describing a completed movement.

        Args:
            data: The validated movement payload that was applied.
            affected: The Inventory row(s) mutated by the movement, in
                the order they were affected (single row for IN/OUT,
                [source, destination] for TRANSFER).

        Returns:
            The event matching this movement's type, carrying the
            post-mutation quantity where applicable.
        """
        if data.movement_type == MovementType.IN:
            assert data.destination_warehouse_id is not None
            return StockReceivedEvent(
                product_id=data.product_id,
                warehouse_id=data.destination_warehouse_id,
                quantity=data.quantity,
                resulting_quantity=affected[0].quantity,
            )
        if data.movement_type == MovementType.OUT:
            assert data.source_warehouse_id is not None
            return StockRemovedEvent(
                product_id=data.product_id,
                warehouse_id=data.source_warehouse_id,
                quantity=data.quantity,
                resulting_quantity=affected[0].quantity,
            )
        assert data.source_warehouse_id is not None
        assert data.destination_warehouse_id is not None
        return StockTransferredEvent(
            product_id=data.product_id,
            source_warehouse_id=data.source_warehouse_id,
            destination_warehouse_id=data.destination_warehouse_id,
            quantity=data.quantity,
        )

    async def _transfer_stock(
        self,
        product_id: uuid.UUID,
        source_warehouse_id: uuid.UUID,
        destination_warehouse_id: uuid.UUID,
        quantity: int,
    ) -> tuple[Inventory, Inventory]:
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

        Returns:
            A (source_inventory, destination_inventory) tuple of the
            two updated Inventory records.

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
            source_inventory = await self._decrease_stock(
                product_id, source_warehouse_id, quantity
            )
            destination_inventory = await self._increase_stock(
                product_id, destination_warehouse_id, quantity
            )
        else:
            destination_inventory = await self._increase_stock(
                product_id, destination_warehouse_id, quantity
            )
            source_inventory = await self._decrease_stock(
                product_id, source_warehouse_id, quantity
            )
        return source_inventory, destination_inventory

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

        inventory = (
            await self.inventory_repository.get_by_product_and_warehouse_for_update(
                product_id, warehouse_id
            )
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

        inventory = (
            await self.inventory_repository.get_by_product_and_warehouse_for_update(
                product_id, warehouse_id
            )
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
