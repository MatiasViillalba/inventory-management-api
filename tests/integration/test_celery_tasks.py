"""Integration tests for Celery task business logic.

Two things about how these tasks are wired make them impossible to
call the way Celery itself would in these tests:

1. Each task module imports `TaskSessionLocal` from app.core.session at
   module load time, bound to the real `DATABASE_URL` — not the
   isolated `_test` database `db_session` uses. Calling a task as-is
   would read and write the development database instead of the test
   one. `patch_task_sessions` fixes this by monkeypatching each task
   module's `TaskSessionLocal` name to a factory that hands back
   `db_session` itself, so task code runs inside the same
   rolled-back transaction as the rest of the test.
2. Each task's public, Celery-decorated entry point is a synchronous
   function that drives its real logic with `asyncio.run(...)` — correct
   for a Celery worker, which has no event loop of its own, but
   `asyncio.run` cannot be called from inside a loop that's already
   running, which every one of these `async def test_...` functions is.
   These tests therefore `await` each task's private `_snake_case`
   async implementation directly instead of calling the public
   `asyncio.run`-wrapped entry point. A couple of "registration" tests
   still call the public function/name to prove the Celery wiring
   itself (task name, the pre-asyncio.run ValueError in
   generate_report_csv) is correct.

The SMTP call in send_low_stock_alert_email is monkeypatched out for
the same reason `.delay()` is elsewhere in this suite: no SMTP catcher
is guaranteed to be running wherever these tests execute, and the SMTP
client library itself is not what this test suite is verifying.
"""

import contextlib
import csv
import logging
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.user import User
from app.models.warehouse import Warehouse
from app.repositories.alert import AlertRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.product import ProductRepository
from app.repositories.user import UserRepository
from app.tasks import monitoring as task_monitoring
from app.tasks.alerts import _check_low_stock_levels, check_low_stock_levels
from app.tasks.notifications import (
    _send_low_stock_alert_email,
    send_low_stock_alert_email,
)
from app.tasks.reports import ReportKind, _generate_report_csv, generate_report_csv


def _make_task_session_factory(
    session: AsyncSession,
) -> Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]]:
    """Build a TaskSessionLocal replacement bound to an existing session.

    Args:
        session: The session every `async with TaskSessionLocal() as s`
            call inside the task under test should receive.

    Returns:
        A zero-argument callable matching TaskSessionLocal's call
        signature, whose async context manager yields `session` without
        closing it (the `db_session` fixture owns that lifecycle).
    """

    @contextlib.asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        yield session

    return _factory


@pytest.fixture
def patch_task_sessions(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Redirect every task module's TaskSessionLocal to the test session."""
    factory = _make_task_session_factory(db_session)
    monkeypatch.setattr("app.tasks.alerts.TaskSessionLocal", factory)
    monkeypatch.setattr("app.tasks.notifications.TaskSessionLocal", factory)
    monkeypatch.setattr("app.tasks.reports.TaskSessionLocal", factory)


class TestCheckLowStockLevelsTask:
    """Tests for the periodic low-stock reconciliation sweep."""

    def test_is_registered_with_expected_name(self) -> None:
        assert check_low_stock_levels.name == "app.tasks.alerts.check_low_stock_levels"

    async def test_reconciles_alert_state_across_all_inventory(
        self,
        db_session: AsyncSession,
        patch_task_sessions: None,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        low_stock_inventory = await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                quantity=1,
                low_stock_threshold=10,
            )
        )
        healthy_product = await ProductRepository(db_session).create(
            Product(sku="TASK-HEALTHY", name="Healthy Item", price=Decimal("1.00"))
        )
        await InventoryRepository(db_session).create(
            Inventory(
                product_id=healthy_product.id,
                warehouse_id=test_warehouse.id,
                quantity=100,
                low_stock_threshold=10,
            )
        )

        summary = await _check_low_stock_levels()

        assert summary["evaluated"] == 2
        assert summary["alerts_active"] == 1

        alert = await AlertRepository(db_session).get_active_by_product_and_warehouse(
            low_stock_inventory.product_id, low_stock_inventory.warehouse_id
        )
        assert alert is not None
        assert alert.alert_type is AlertType.LOW_STOCK


class TestSendLowStockAlertEmailTask:
    """Tests for the low-stock notification email task."""

    def test_is_registered_with_expected_name(self) -> None:
        assert (
            send_low_stock_alert_email.name
            == "app.tasks.notifications.send_low_stock_alert_email"
        )

    async def test_emails_active_superusers(
        self,
        db_session: AsyncSession,
        patch_task_sessions: None,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent_emails: list[dict] = []
        monkeypatch.setattr(
            "app.tasks.notifications.send_email",
            lambda **kwargs: sent_emails.append(kwargs),
        )
        active_superuser = await UserRepository(db_session).create(
            User(
                email="active.super@example.com",
                hashed_password="hashed",
                full_name="Active Super",
                is_active=True,
                is_superuser=True,
            )
        )
        await UserRepository(db_session).create(
            User(
                email="inactive.super@example.com",
                hashed_password="hashed",
                full_name="Inactive Super",
                is_active=False,
                is_superuser=True,
            )
        )
        alert = await AlertRepository(db_session).create(
            Alert(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                alert_type=AlertType.LOW_STOCK,
                status=AlertStatus.ACTIVE,
                threshold=10,
                quantity_at_trigger=3,
            )
        )

        await _send_low_stock_alert_email(alert.id)

        assert len(sent_emails) == 1
        assert sent_emails[0]["to"] == [active_superuser.email]
        assert test_product.name in sent_emails[0]["subject"]

    async def test_skips_when_no_active_superusers(
        self,
        db_session: AsyncSession,
        patch_task_sessions: None,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent_emails: list[dict] = []
        monkeypatch.setattr(
            "app.tasks.notifications.send_email",
            lambda **kwargs: sent_emails.append(kwargs),
        )
        alert = await AlertRepository(db_session).create(
            Alert(
                product_id=test_product.id,
                warehouse_id=test_warehouse.id,
                alert_type=AlertType.OUT_OF_STOCK,
                status=AlertStatus.ACTIVE,
                threshold=10,
                quantity_at_trigger=0,
            )
        )

        await _send_low_stock_alert_email(alert.id)

        assert sent_emails == []


class TestGenerateReportCsvTask:
    """Tests for the CSV report export task."""

    def test_is_registered_with_expected_name(self) -> None:
        assert generate_report_csv.name == "app.tasks.reports.generate_report_csv"

    def test_rejects_unknown_report_kind(self) -> None:
        # No asyncio.run(...) is reached for an invalid kind (ReportKind(...)
        # raises first), so calling the sync entry point directly is safe
        # even though this test function is itself already running inside
        # an event loop.
        with pytest.raises(ValueError):
            generate_report_csv("not-a-real-report")

    async def test_generates_inventory_summary_csv(
        self,
        db_session: AsyncSession,
        patch_task_sessions: None,
        test_product: Product,
        test_warehouse: Warehouse,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "reports_storage_dir", str(tmp_path))
        await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=7
            )
        )

        result = await _generate_report_csv(ReportKind.INVENTORY_SUMMARY)

        assert result["report_kind"] == "inventory_summary"
        file_path = Path(result["file_path"])
        assert file_path.exists()
        with file_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        matching = next(
            row for row in rows if row["warehouse_id"] == str(test_warehouse.id)
        )
        assert matching["total_quantity"] == "7"

    async def test_generates_valuation_csv(
        self,
        db_session: AsyncSession,
        patch_task_sessions: None,
        test_product: Product,
        test_warehouse: Warehouse,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "reports_storage_dir", str(tmp_path))
        await InventoryRepository(db_session).create(
            Inventory(
                product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=4
            )
        )

        result = await _generate_report_csv(ReportKind.VALUATION)

        assert result["report_kind"] == "valuation"
        file_path = Path(result["file_path"])
        with file_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        matching = next(
            row for row in rows if row["warehouse_id"] == str(test_warehouse.id)
        )
        assert Decimal(matching["total_value"]) == test_product.price * 4


class TestTaskMonitoringSignals:
    """Tests for the Celery signal handlers that log task lifecycle events."""

    def test_prerun_and_postrun_log_duration(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        dummy_task = SimpleNamespace(name="app.tasks.demo.dummy_task")
        with caplog.at_level(logging.INFO, logger="app.tasks.monitoring"):
            task_monitoring._on_task_prerun(task_id="task-1", task=dummy_task)
            task_monitoring._on_task_postrun(
                task_id="task-1", task=dummy_task, state="SUCCESS"
            )

        messages = [record.message for record in caplog.records]
        assert any("Task started" in message for message in messages)
        finished_record = next(
            record for record in caplog.records if "Task finished" in record.message
        )
        assert finished_record.duration_ms is not None
        assert finished_record.duration_ms >= 0

    def test_failure_logs_at_error_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        dummy_task = SimpleNamespace(name="app.tasks.demo.dummy_task")
        with caplog.at_level(logging.ERROR, logger="app.tasks.monitoring"):
            task_monitoring._on_task_failure(
                task_id="task-2", sender=dummy_task, exception=ValueError("boom")
            )

        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def test_retry_logs_at_warning_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        dummy_task = SimpleNamespace(name="app.tasks.demo.dummy_task")
        dummy_request = SimpleNamespace(id="task-3")
        with caplog.at_level(logging.WARNING, logger="app.tasks.monitoring"):
            task_monitoring._on_task_retry(
                request=dummy_request, sender=dummy_task, reason="temporary failure"
            )

        assert any(record.levelno == logging.WARNING for record in caplog.records)
