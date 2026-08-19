"""Read endpoints for aggregate inventory reports.

Backed by ReportService, which computes figures on demand with
database-side aggregation. Reports are stateless and side-effect free,
so every route here is a GET.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db
from app.schemas.report import InventorySummaryReport, InventoryValuationReport
from app.services.report import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/inventory-summary", response_model=InventorySummaryReport)
async def get_inventory_summary(
    db: AsyncSession = Depends(get_db),
) -> InventorySummaryReport:
    """Report current stock quantity and low-stock figures per warehouse.

    Args:
        db: Injected async database session.

    Returns:
        InventorySummaryReport: Global and per-warehouse stock figures.
    """
    service = ReportService(db)
    return await service.generate_inventory_summary()


@router.get("/valuation", response_model=InventoryValuationReport)
async def get_valuation_report(
    db: AsyncSession = Depends(get_db),
) -> InventoryValuationReport:
    """Report current inventory valuation (quantity * unit price) per warehouse.

    Args:
        db: Injected async database session.

    Returns:
        InventoryValuationReport: Global and per-warehouse inventory value.
    """
    service = ReportService(db)
    return await service.generate_valuation_report()
