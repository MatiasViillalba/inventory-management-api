"""Celery task for generating downloadable inventory reports.

Report figures are already computed cheaply by ReportService via
database-side aggregation (see app/services/report.py). This task
covers the export step on top of that: rendering the computed report
into a CSV file and persisting it to disk. For a large catalog that
file I/O is slow enough that it belongs off the request/response
cycle, which is also why this exists as a separate task rather than
being folded into the existing GET /reports endpoints.
"""

import asyncio
import csv
import enum
import logging
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.session import TaskSessionLocal
from app.schemas.report import InventorySummaryReport, InventoryValuationReport
from app.services.report import ReportService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


class ReportKind(str, enum.Enum):
    """The kind of report a generation task run can produce."""

    INVENTORY_SUMMARY = "inventory_summary"
    VALUATION = "valuation"


@celery_app.task(name="app.tasks.reports.generate_report_csv")
def generate_report_csv(report_kind: str) -> dict[str, str]:
    """Generate a report as a CSV file and persist it to disk.

    Args:
        report_kind: The value of a ReportKind member identifying
            which report to generate (e.g. "inventory_summary").

    Returns:
        dict[str, str]: The report kind and the path of the generated
        file, so a caller (e.g. a status-polling endpoint added in a
        later commit) can locate the output once the task completes.

    Raises:
        ValueError: If report_kind is not a recognized ReportKind value.
    """
    kind = ReportKind(report_kind)
    return asyncio.run(_generate_report_csv(kind))


async def _generate_report_csv(kind: ReportKind) -> dict[str, str]:
    """Async implementation: compute the report, then write it to CSV.

    Opens a database session scoped to this task run rather than
    reusing any FastAPI request-scoped session.

    Args:
        kind: The report to generate.

    Returns:
        dict[str, str]: The report kind and the generated file's path.
    """
    async with TaskSessionLocal() as session:
        service = ReportService(session)
        if kind == ReportKind.INVENTORY_SUMMARY:
            file_path = _write_inventory_summary_csv(
                await service.generate_inventory_summary()
            )
        else:
            file_path = _write_valuation_csv(await service.generate_valuation_report())

    logger.info("Generated %s report at %s", kind.value, file_path)
    return {"report_kind": kind.value, "file_path": str(file_path)}


def _reports_dir() -> Path:
    """Return the directory reports are written to, creating it if needed.

    Returns:
        Path: The reports storage directory.
    """
    directory = Path(get_settings().reports_storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_inventory_summary_csv(report: InventorySummaryReport) -> Path:
    """Write an InventorySummaryReport to a new CSV file.

    Args:
        report: The computed inventory summary report.

    Returns:
        Path: The path of the written CSV file.
    """
    file_path = _reports_dir() / f"inventory_summary_{uuid.uuid4().hex}.csv"
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "warehouse_id",
                "warehouse_name",
                "distinct_products",
                "total_quantity",
                "low_stock_count",
                "out_of_stock_count",
            ]
        )
        for row in report.by_warehouse:
            writer.writerow(
                [
                    row.warehouse_id,
                    row.warehouse_name,
                    row.distinct_products,
                    row.total_quantity,
                    row.low_stock_count,
                    row.out_of_stock_count,
                ]
            )
    return file_path


def _write_valuation_csv(report: InventoryValuationReport) -> Path:
    """Write an InventoryValuationReport to a new CSV file.

    Args:
        report: The computed inventory valuation report.

    Returns:
        Path: The path of the written CSV file.
    """
    file_path = _reports_dir() / f"valuation_{uuid.uuid4().hex}.csv"
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["warehouse_id", "warehouse_name", "total_value"])
        for row in report.by_warehouse:
            writer.writerow([row.warehouse_id, row.warehouse_name, row.total_value])
    return file_path
