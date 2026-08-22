"""Unit tests for the repository layer.

BaseRepository's generic CRUD behavior is exercised once through
WarehouseRepository rather than duplicated per concrete repository,
since every repository inherits the same implementation unmodified.
Each concrete repository's own tests then focus only on the
model-specific queries it adds (natural-key lookups, filtering,
ordering), which is where repository-specific bugs actually live.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.inventory import Inventory
from app.models.movement import Movement, MovementType
from app.models.product import Product
from app.models.user import User
from app.models.warehouse import Warehouse
from app.repositories.alert import AlertRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.movement import MovementRepository
from app.repositories.product import ProductRepository
from app.repositories.user import UserRepository
from app.repositories.warehouse import WarehouseRepository


class TestBaseRepositoryCrud:
    """Tests for the generic CRUD methods inherited from BaseRepository."""

    async def test_create_persists_and_returns_entity_with_generated_id(
        self, db_session: AsyncSession
    ) -> None:
        repository = WarehouseRepository(db_session)
        warehouse = await repository.create(Warehouse(name="Depot", code="BASE-1"))

        assert isinstance(warehouse.id, uuid.UUID)

    async def test_get_by_id_returns_entity(self, db_session: AsyncSession) -> None:
        repository = WarehouseRepository(db_session)
        created = await repository.create(Warehouse(name="Depot", code="BASE-2"))

        fetched = await repository.get_by_id(created.id)

        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_by_id_returns_none_when_missing(self, db_session: AsyncSession) -> None:
        repository = WarehouseRepository(db_session)

        fetched = await repository.get_by_id(uuid.uuid4())

        assert fetched is None

    async def test_get_by_id_or_raise_raises_not_found_error(
        self, db_session: AsyncSession
    ) -> None:
        repository = WarehouseRepository(db_session)

        with pytest.raises(NotFoundError):
            await repository.get_by_id_or_raise(uuid.uuid4())

    async def test_list_all_respects_skip_and_limit(self, db_session: AsyncSession) -> None:
        repository = WarehouseRepository(db_session)
        for index in range(3):
            await repository.create(Warehouse(name=f"Depot {index}", code=f"BASE-LIST-{index}"))

        page = await repository.list_all(skip=1, limit=1)

        assert len(page) == 1

    async def test_delete_removes_entity(self, db_session: AsyncSession) -> None:
        repository = WarehouseRepository(db_session)
        created = await repository.create(Warehouse(name="Depot", code="BASE-3"))

        await repository.delete(created)

        assert await repository.get_by_id(created.id) is None


class TestWarehouseRepository:
    """Tests for WarehouseRepository's warehouse-specific queries."""

    async def test_get_by_code_returns_match(self, db_session: AsyncSession) -> None:
        repository = WarehouseRepository(db_session)
        await repository.create(Warehouse(name="Depot", code="WH-CODE-1"))

        found = await repository.get_by_code("WH-CODE-1")

        assert found is not None
        assert found.code == "WH-CODE-1"

    async def test_get_by_code_returns_none_when_missing(self, db_session: AsyncSession) -> None:
        repository = WarehouseRepository(db_session)

        found = await repository.get_by_code("NO-SUCH-CODE")

        assert found is None

    async def test_list_active_excludes_inactive(self, db_session: AsyncSession) -> None:
        repository = WarehouseRepository(db_session)
        await repository.create(Warehouse(name="Active Depot", code="WH-ACTIVE", is_active=True))
        await repository.create(
            Warehouse(name="Inactive Depot", code="WH-INACTIVE", is_active=False)
        )

        active = await repository.list_active()

        codes = {warehouse.code for warehouse in active}
        assert "WH-ACTIVE" in codes
        assert "WH-INACTIVE" not in codes


class TestProductRepository:
    """Tests for ProductRepository's product-specific queries."""

    async def test_get_by_sku_returns_match(self, db_session: AsyncSession) -> None:
        repository = ProductRepository(db_session)
        await repository.create(Product(sku="SKU-REPO-1", name="Widget", price=Decimal("1.00")))

        found = await repository.get_by_sku("SKU-REPO-1")

        assert found is not None
        assert found.sku == "SKU-REPO-1"

    async def test_list_active_excludes_inactive(self, db_session: AsyncSession) -> None:
        repository = ProductRepository(db_session)
        await repository.create(
            Product(sku="SKU-ACTIVE", name="Widget", price=Decimal("1.00"), is_active=True)
        )
        await repository.create(
            Product(sku="SKU-INACTIVE", name="Gadget", price=Decimal("1.00"), is_active=False)
        )

        active = await repository.list_active()

        skus = {product.sku for product in active}
        assert "SKU-ACTIVE" in skus
        assert "SKU-INACTIVE" not in skus

    async def test_search_by_name_is_case_insensitive(self, db_session: AsyncSession) -> None:
        repository = ProductRepository(db_session)
        await repository.create(
            Product(sku="SKU-SEARCH", name="Wireless Mouse", price=Decimal("1.00"))
        )

        results = await repository.search_by_name("wireless")

        assert any(product.sku == "SKU-SEARCH" for product in results)


class TestInventoryRepository:
    """Tests for InventoryRepository's inventory-specific queries."""

    async def test_get_by_product_and_warehouse_returns_match(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        repository = InventoryRepository(db_session)
        await repository.create(
            Inventory(product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=15)
        )

        found = await repository.get_by_product_and_warehouse(test_product.id, test_warehouse.id)

        assert found is not None
        assert found.quantity == 15

    async def test_get_by_product_and_warehouse_for_update_returns_match(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        repository = InventoryRepository(db_session)
        await repository.create(
            Inventory(product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=15)
        )

        locked = await repository.get_by_product_and_warehouse_for_update(
            test_product.id, test_warehouse.id
        )

        assert locked is not None
        assert locked.quantity == 15

    async def test_list_by_warehouse(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        repository = InventoryRepository(db_session)
        await repository.create(
            Inventory(product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=5)
        )

        records = await repository.list_by_warehouse(test_warehouse.id)

        assert len(records) == 1

    async def test_list_low_stock_only_includes_records_at_or_below_threshold(
        self, db_session: AsyncSession, test_warehouse: Warehouse
    ) -> None:
        product_repository = ProductRepository(db_session)
        inventory_repository = InventoryRepository(db_session)

        low_stock_product = await product_repository.create(
            Product(sku="SKU-LOW", name="Low Stock Item", price=Decimal("1.00"))
        )
        healthy_product = await product_repository.create(
            Product(sku="SKU-HEALTHY", name="Healthy Item", price=Decimal("1.00"))
        )
        unmonitored_product = await product_repository.create(
            Product(sku="SKU-UNMONITORED", name="Unmonitored Item", price=Decimal("1.00"))
        )

        await inventory_repository.create(
            Inventory(
                product_id=low_stock_product.id,
                warehouse_id=test_warehouse.id,
                quantity=2,
                low_stock_threshold=10,
            )
        )
        await inventory_repository.create(
            Inventory(
                product_id=healthy_product.id,
                warehouse_id=test_warehouse.id,
                quantity=50,
                low_stock_threshold=10,
            )
        )
        await inventory_repository.create(
            Inventory(
                product_id=unmonitored_product.id,
                warehouse_id=test_warehouse.id,
                quantity=0,
                low_stock_threshold=None,
            )
        )

        low_stock = await inventory_repository.list_low_stock()

        product_ids = {record.product_id for record in low_stock}
        assert low_stock_product.id in product_ids
        assert healthy_product.id not in product_ids
        assert unmonitored_product.id not in product_ids


class TestMovementRepository:
    """Tests for MovementRepository's audit-trail queries."""

    async def test_list_by_product_orders_most_recent_first(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        # created_at is set explicitly here because Postgres' now() returns
        # the same value for every statement within one transaction, and
        # the whole test runs inside a single transaction (see db_session
        # in conftest.py) — without distinct timestamps, ordering between
        # the two rows below would be undefined.
        repository = MovementRepository(db_session)
        now = datetime.now(timezone.utc)
        first = await repository.create(
            Movement(
                product_id=test_product.id,
                movement_type=MovementType.IN,
                quantity=10,
                destination_warehouse_id=test_warehouse.id,
                created_at=now - timedelta(minutes=5),
            )
        )
        second = await repository.create(
            Movement(
                product_id=test_product.id,
                movement_type=MovementType.IN,
                quantity=5,
                destination_warehouse_id=test_warehouse.id,
                created_at=now,
            )
        )

        movements = await repository.list_by_product(test_product.id)

        assert [movement.id for movement in movements[:2]] == [second.id, first.id]

    async def test_list_by_warehouse_matches_source_or_destination(
        self, db_session: AsyncSession, test_product: Product
    ) -> None:
        warehouse_repository = WarehouseRepository(db_session)
        movement_repository = MovementRepository(db_session)
        source = await warehouse_repository.create(Warehouse(name="Source", code="MOVE-SRC"))
        destination = await warehouse_repository.create(
            Warehouse(name="Destination", code="MOVE-DST")
        )
        await movement_repository.create(
            Movement(
                product_id=test_product.id,
                movement_type=MovementType.TRANSFER,
                quantity=3,
                source_warehouse_id=source.id,
                destination_warehouse_id=destination.id,
            )
        )

        by_source = await movement_repository.list_by_warehouse(source.id)
        by_destination = await movement_repository.list_by_warehouse(destination.id)

        assert len(by_source) == 1
        assert len(by_destination) == 1


class TestAlertRepository:
    """Tests for AlertRepository's alert-status queries."""

    async def test_get_active_by_product_and_warehouse_ignores_resolved_alerts(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        repository = AlertRepository(db_session)
        await repository.create(
            Alert(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                alert_type=AlertType.LOW_STOCK,
                status=AlertStatus.RESOLVED,
                threshold=10,
                quantity_at_trigger=2,
            )
        )

        found = await repository.get_active_by_product_and_warehouse(
            test_product.id, test_warehouse.id
        )

        assert found is None

    async def test_list_active_excludes_resolved(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        repository = AlertRepository(db_session)
        active = await repository.create(
            Alert(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                alert_type=AlertType.LOW_STOCK,
                status=AlertStatus.ACTIVE,
                threshold=10,
                quantity_at_trigger=2,
            )
        )
        await repository.create(
            Alert(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                alert_type=AlertType.OUT_OF_STOCK,
                status=AlertStatus.RESOLVED,
                threshold=10,
                quantity_at_trigger=0,
            )
        )

        active_alerts = await repository.list_active()

        alert_ids = {alert.id for alert in active_alerts}
        assert active.id in alert_ids
        assert len(active_alerts) == 1


class TestUserRepository:
    """Tests for UserRepository's authentication-related queries."""

    async def test_get_by_email_returns_match(self, db_session: AsyncSession) -> None:
        repository = UserRepository(db_session)
        await repository.create(
            User(email="repo.user@example.com", hashed_password="hashed", full_name="Repo User")
        )

        found = await repository.get_by_email("repo.user@example.com")

        assert found is not None
        assert found.email == "repo.user@example.com"

    async def test_list_active_superusers_excludes_inactive_and_non_superusers(
        self, db_session: AsyncSession
    ) -> None:
        repository = UserRepository(db_session)
        active_superuser = await repository.create(
            User(
                email="active.super@example.com",
                hashed_password="hashed",
                full_name="Active Super",
                is_active=True,
                is_superuser=True,
            )
        )
        await repository.create(
            User(
                email="inactive.super@example.com",
                hashed_password="hashed",
                full_name="Inactive Super",
                is_active=False,
                is_superuser=True,
            )
        )
        await repository.create(
            User(
                email="active.regular@example.com",
                hashed_password="hashed",
                full_name="Active Regular",
                is_active=True,
                is_superuser=False,
            )
        )

        superusers = await repository.list_active_superusers()

        user_ids = {user.id for user in superusers}
        assert active_superuser.id in user_ids
        assert len(superusers) == 1
