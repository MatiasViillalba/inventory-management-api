"""Unit tests for the service layer.

Services own transaction boundaries and business rules, so these tests
exercise them against the real test database (via `db_session`) rather
than mocking the repository layer: the behavior under test — conflict
detection, row-locked stock arithmetic, alert state transitions — is
only meaningful in terms of what actually lands in the database.

The one external dependency worth isolating is the Celery broker: alert
notifications are enqueued with `.delay()`, which would otherwise try to
talk to a real broker connection during a "unit" test. That call is
monkeypatched out in the alert-related tests below.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    InsufficientStockError,
    NotFoundError,
)
from app.events.base import DomainEvent, EventPublisher
from app.events.publisher import InProcessEventPublisher
from app.models.alert import AlertStatus, AlertType
from app.models.inventory import Inventory
from app.models.movement import MovementType
from app.models.product import Product
from app.models.warehouse import Warehouse
from app.repositories.alert import AlertRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.warehouse import WarehouseRepository
from app.schemas.movement import MovementCreate
from app.schemas.product import ProductCreate, ProductUpdate
from app.schemas.warehouse import WarehouseCreate, WarehouseUpdate
from app.services.alert import AlertService
from app.services.inventory_command import InventoryCommandService
from app.services.inventory_query import InventoryQueryService
from app.services.product import ProductService
from app.services.report import ReportService
from app.services.warehouse import WarehouseService


@pytest.fixture
def event_publisher() -> EventPublisher:
    """A fresh in-process publisher, isolated per test."""
    return InProcessEventPublisher()


class TestWarehouseService:
    """Tests for WarehouseService's business rules."""

    async def test_create_warehouse_persists(self, db_session: AsyncSession) -> None:
        service = WarehouseService(db_session)

        warehouse = await service.create_warehouse(
            WarehouseCreate(name="Depot", code="SVC-WH-1")
        )

        assert warehouse.id is not None

    async def test_create_warehouse_raises_conflict_on_duplicate_code(
        self, db_session: AsyncSession
    ) -> None:
        service = WarehouseService(db_session)
        await service.create_warehouse(WarehouseCreate(name="Depot", code="SVC-WH-DUP"))

        with pytest.raises(ConflictError):
            await service.create_warehouse(WarehouseCreate(name="Other Depot", code="SVC-WH-DUP"))

    async def test_get_warehouse_raises_not_found(self, db_session: AsyncSession) -> None:
        service = WarehouseService(db_session)

        with pytest.raises(NotFoundError):
            await service.get_warehouse(uuid.uuid4())

    async def test_list_warehouses_active_only_excludes_inactive(
        self, db_session: AsyncSession
    ) -> None:
        service = WarehouseService(db_session)
        await service.create_warehouse(WarehouseCreate(name="Active", code="SVC-WH-ACTIVE"))
        inactive = await service.create_warehouse(
            WarehouseCreate(name="Inactive", code="SVC-WH-INACTIVE")
        )
        await service.deactivate_warehouse(inactive.id)

        active_only = await service.list_warehouses(active_only=True)

        codes = {warehouse.code for warehouse in active_only}
        assert "SVC-WH-ACTIVE" in codes
        assert "SVC-WH-INACTIVE" not in codes

    async def test_update_warehouse_raises_conflict_on_duplicate_code(
        self, db_session: AsyncSession
    ) -> None:
        service = WarehouseService(db_session)
        await service.create_warehouse(WarehouseCreate(name="Depot A", code="SVC-WH-A"))
        depot_b = await service.create_warehouse(WarehouseCreate(name="Depot B", code="SVC-WH-B"))

        with pytest.raises(ConflictError):
            await service.update_warehouse(depot_b.id, WarehouseUpdate(code="SVC-WH-A"))

    async def test_update_warehouse_applies_fields(self, db_session: AsyncSession) -> None:
        service = WarehouseService(db_session)
        warehouse = await service.create_warehouse(WarehouseCreate(name="Depot", code="SVC-WH-U"))

        updated = await service.update_warehouse(
            warehouse.id, WarehouseUpdate(name="Renamed Depot")
        )

        assert updated.name == "Renamed Depot"
        assert updated.code == "SVC-WH-U"

    async def test_deactivate_warehouse_sets_inactive(self, db_session: AsyncSession) -> None:
        service = WarehouseService(db_session)
        warehouse = await service.create_warehouse(WarehouseCreate(name="Depot", code="SVC-WH-D"))

        deactivated = await service.deactivate_warehouse(warehouse.id)

        assert deactivated.is_active is False


class TestProductService:
    """Tests for ProductService's business rules."""

    async def test_create_product_raises_conflict_on_duplicate_sku(
        self, db_session: AsyncSession
    ) -> None:
        service = ProductService(db_session)
        await service.create_product(
            ProductCreate(sku="SVC-SKU-DUP", name="Widget", price=Decimal("1.00"))
        )

        with pytest.raises(ConflictError):
            await service.create_product(
                ProductCreate(sku="SVC-SKU-DUP", name="Other Widget", price=Decimal("2.00"))
            )

    async def test_update_product_raises_conflict_on_duplicate_sku(
        self, db_session: AsyncSession
    ) -> None:
        service = ProductService(db_session)
        await service.create_product(
            ProductCreate(sku="SVC-SKU-A", name="Widget A", price=Decimal("1.00"))
        )
        product_b = await service.create_product(
            ProductCreate(sku="SVC-SKU-B", name="Widget B", price=Decimal("1.00"))
        )

        with pytest.raises(ConflictError):
            await service.update_product(product_b.id, ProductUpdate(sku="SVC-SKU-A"))

    async def test_search_products_matches_partial_name(self, db_session: AsyncSession) -> None:
        service = ProductService(db_session)
        await service.create_product(
            ProductCreate(sku="SVC-SKU-SEARCH", name="Mechanical Keyboard", price=Decimal("1.00"))
        )

        results = await service.search_products("keyboard")

        assert any(product.sku == "SVC-SKU-SEARCH" for product in results)

    async def test_deactivate_product_sets_inactive(self, db_session: AsyncSession) -> None:
        service = ProductService(db_session)
        product = await service.create_product(
            ProductCreate(sku="SVC-SKU-D", name="Widget", price=Decimal("1.00"))
        )

        deactivated = await service.deactivate_product(product.id)

        assert deactivated.is_active is False


class TestInventoryQueryService:
    """Tests for InventoryQueryService's read-only queries."""

    async def test_get_stock_level_raises_not_found_when_missing(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        service = InventoryQueryService(db_session)

        with pytest.raises(NotFoundError):
            await service.get_stock_level(test_product.id, test_warehouse.id)

    async def test_list_low_stock_reflects_repository(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=1,
                low_stock_threshold=5,
            )
        )
        service = InventoryQueryService(db_session)

        low_stock = await service.list_low_stock()

        assert any(record.product_id == test_product.id for record in low_stock)


class TestInventoryCommandService:
    """Tests for InventoryCommandService's stock-mutating operations."""

    async def test_in_movement_creates_stock_and_movement_record(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        service = InventoryCommandService(db_session, event_publisher)

        movement = await service.record_movement(
            MovementCreate(
                product_id=test_product.id,
                movement_type=MovementType.IN,
                quantity=50,
                destination_warehouse_id=test_warehouse.id,
            )
        )

        assert movement.quantity == 50
        stock = await InventoryQueryService(db_session).get_stock_level(
            test_product.id, test_warehouse.id
        )
        assert stock.quantity == 50

    async def test_out_movement_raises_insufficient_stock(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        service = InventoryCommandService(db_session, event_publisher)
        await service.record_movement(
            MovementCreate(
                product_id=test_product.id,
                movement_type=MovementType.IN,
                quantity=5,
                destination_warehouse_id=test_warehouse.id,
            )
        )

        with pytest.raises(InsufficientStockError):
            await service.record_movement(
                MovementCreate(
                    product_id=test_product.id,
                    movement_type=MovementType.OUT,
                    quantity=10,
                    source_warehouse_id=test_warehouse.id,
                )
            )

    async def test_out_movement_raises_not_found_without_existing_stock(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
    ) -> None:
        service = InventoryCommandService(db_session, event_publisher)

        with pytest.raises(NotFoundError):
            await service.record_movement(
                MovementCreate(
                    product_id=test_product.id,
                    movement_type=MovementType.OUT,
                    quantity=1,
                    source_warehouse_id=test_warehouse.id,
                )
            )

    async def test_record_movement_raises_not_found_for_missing_product(
        self, db_session: AsyncSession, event_publisher: EventPublisher, test_warehouse: Warehouse
    ) -> None:
        service = InventoryCommandService(db_session, event_publisher)

        with pytest.raises(NotFoundError):
            await service.record_movement(
                MovementCreate(
                    product_id=uuid.uuid4(),
                    movement_type=MovementType.IN,
                    quantity=1,
                    destination_warehouse_id=test_warehouse.id,
                )
            )

    async def test_transfer_movement_moves_stock_between_warehouses(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        warehouse_repository = WarehouseRepository(db_session)
        source = await warehouse_repository.create(Warehouse(name="Source", code="SVC-XFER-SRC"))
        destination = await warehouse_repository.create(
            Warehouse(name="Destination", code="SVC-XFER-DST")
        )
        service = InventoryCommandService(db_session, event_publisher)
        await service.record_movement(
            MovementCreate(
                product_id=test_product.id,
                movement_type=MovementType.IN,
                quantity=20,
                destination_warehouse_id=source.id,
            )
        )

        await service.record_movement(
            MovementCreate(
                product_id=test_product.id,
                movement_type=MovementType.TRANSFER,
                quantity=8,
                source_warehouse_id=source.id,
                destination_warehouse_id=destination.id,
            )
        )

        query_service = InventoryQueryService(db_session)
        source_stock = await query_service.get_stock_level(test_product.id, source.id)
        destination_stock = await query_service.get_stock_level(test_product.id, destination.id)
        assert source_stock.quantity == 12
        assert destination_stock.quantity == 8

    async def test_record_movement_publishes_domain_event(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        published: list[DomainEvent] = []

        async def _capture(event: DomainEvent) -> None:
            published.append(event)

        event_publisher.subscribe("inventory.stock_received", _capture)
        service = InventoryCommandService(db_session, event_publisher)

        await service.record_movement(
            MovementCreate(
                product_id=test_product.id,
                movement_type=MovementType.IN,
                quantity=15,
                destination_warehouse_id=test_warehouse.id,
            )
        )

        assert len(published) == 1
        assert published[0].event_type == "inventory.stock_received"

    async def test_record_movement_below_threshold_creates_low_stock_alert(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        service = InventoryCommandService(db_session, event_publisher)

        # Global default low-stock threshold (settings.low_stock_alert_threshold_default)
        # is 10, so an inbound quantity below that should raise a LOW_STOCK alert.
        await service.record_movement(
            MovementCreate(
                product_id=test_product.id,
                movement_type=MovementType.IN,
                quantity=3,
                destination_warehouse_id=test_warehouse.id,
            )
        )

        alert = await AlertRepository(db_session).get_active_by_product_and_warehouse(
            test_product.id, test_warehouse.id
        )
        assert alert is not None
        assert alert.alert_type is AlertType.LOW_STOCK


class TestAlertService:
    """Tests for AlertService's alert lifecycle logic."""

    async def test_evaluate_stock_level_creates_alert_below_threshold(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        inventory = await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=2,
                low_stock_threshold=10,
            )
        )
        service = AlertService(db_session, event_publisher)

        alert = await service.evaluate_stock_level(inventory)

        assert alert is not None
        assert alert.status is AlertStatus.ACTIVE
        assert alert.alert_type is AlertType.LOW_STOCK

    async def test_evaluate_stock_level_escalates_to_out_of_stock(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        inventory = await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=2,
                low_stock_threshold=10,
            )
        )
        service = AlertService(db_session, event_publisher)
        await service.evaluate_stock_level(inventory)

        inventory.quantity = 0
        await db_session.flush()
        escalated = await service.evaluate_stock_level(inventory)

        assert escalated is not None
        assert escalated.alert_type is AlertType.OUT_OF_STOCK

    async def test_evaluate_stock_level_resolves_alert_when_stock_recovers(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        inventory = await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=2,
                low_stock_threshold=10,
            )
        )
        service = AlertService(db_session, event_publisher)
        await service.evaluate_stock_level(inventory)

        inventory.quantity = 100
        await db_session.flush()
        result = await service.evaluate_stock_level(inventory)

        assert result is None
        remaining = await AlertRepository(db_session).get_active_by_product_and_warehouse(
            test_product.id, test_warehouse.id
        )
        assert remaining is None

    async def test_resolve_alert_raises_conflict_when_already_resolved(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        inventory = await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=2,
                low_stock_threshold=10,
            )
        )
        service = AlertService(db_session, event_publisher)
        alert = await service.evaluate_stock_level(inventory)
        assert alert is not None
        await service.resolve_alert(alert.id)

        with pytest.raises(ConflictError):
            await service.resolve_alert(alert.id)

    async def test_evaluate_stock_level_enqueues_notification(
        self,
        db_session: AsyncSession,
        event_publisher: EventPublisher,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay",
            lambda alert_id: calls.append(alert_id),
        )
        inventory = await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=2,
                low_stock_threshold=10,
            )
        )
        service = AlertService(db_session, event_publisher)

        await service.evaluate_stock_level(inventory)

        assert len(calls) == 1


class TestReportService:
    """Tests for ReportService's database-side aggregations."""

    async def test_generate_inventory_summary_aggregates_by_warehouse(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=3,
                low_stock_threshold=10,
            )
        )
        service = ReportService(db_session)

        report = await service.generate_inventory_summary()

        warehouse_summary = next(
            row for row in report.by_warehouse if row.warehouse_id == test_warehouse.id
        )
        assert warehouse_summary.total_quantity == 3
        assert warehouse_summary.low_stock_count == 1

    async def test_generate_valuation_report_computes_total_value(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        await InventoryRepository(db_session).create(
            Inventory(product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=10)
        )
        service = ReportService(db_session)

        report = await service.generate_valuation_report()

        expected_value = test_product.price * 10
        warehouse_valuation = next(
            row for row in report.by_warehouse if row.warehouse_id == test_warehouse.id
        )
        assert warehouse_valuation.total_value == expected_value
